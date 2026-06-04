Mensch wurde benachrichtigt, dass Hot leer läuft
Proxmox Host
    psbt_usbFlow hot

Auf Hot
    sudo API_BASE="http://middleware.btc-hot.svc.cluster.local:8080" \
    API_TOKEN="..." \
    psbt-export.sh <intent-id>
Start cold workflow


# README — Hot Auto‑Signing + Cold Manual Refill (Air‑gapped)

**Kubernetes/Talos on Proxmox + regtest network simulation + Proxmox USB attach/detach**

> **Zielbild (kurz):**
>
> *   **Hot‑Flow (extern, vollautomatisch):** Externe Requests → OPA Policy → **Policy‑Signer signiert** → Bitcoin Core (node-only) broadcastet
> *   **Cold‑Flow (manual refill):** Threshold triggert Refill‑Intent → Notification (ntfy, out-of-scope) → Mensch exportiert PSBT auf USB → **Air‑gapped Approval + Signing** (Signer + KeyB/KeyC) → final PSBT → Broadcast

***

## 1) Architektur-Übersicht

### 1.1 Namespaces / Trust Boundaries

*   **`btc-hot` (online, Kubernetes/Talos)**  
    Enthält: `middleware`, `tx-builder`, `policy-signer`, `opa`, `nats` (+ optional RPC-gateway)
*   **`btc-net` (Bitcoin Netz Simulation, Kubernetes/Talos)**  
    Enthält: `bitcoind-regtest` (node-only), `regtest-miner`

### 1.2 Offline / Air‑gapped (Proxmox VMs)

*   **`signer` VM (offline)**: GPG Private Key für Approval (kein BTC Key)
*   **`keyB` VM (offline)**: BTC KeyB (Sparrow), Signer Public Key importiert
*   **`keyC` VM (offline)**: BTC KeyC (Sparrow), Signer Public Key importiert
*   **Proxmox Host**: simuliert USB „einstecken/abziehen“ via `psbt_usbFlow` (attach/detach)

***

## 2) Repository-Struktur (Orderstruktur)

```text
repo/
  README.md

  contracts/
    openapi/
      middleware.yaml
      tx-builder.yaml
      policy-signer.yaml
      notifier.yaml
      rpc-gateway.yaml
    asyncapi/
      nats.yaml
    schemas/
      intent.json
      tx_state.json
      psbt_payload.json
    examples/
      http/
        create_hot_tx.request.json
        create_hot_tx.response.json
        get_psbt_base64.response.json
      nats/
        intent_refill_created.json
        tx_hot_requested.json
    VERSIONING.md

  policies/
    hot.rego
    refill.rego
    data.json

  deploy/
    k8s/
      base/
        namespace.yaml
        configmap.yaml
        secrets-template.yaml
        nats.yaml
        opa.yaml
        middleware.yaml
        tx-builder.yaml
        policy-signer.yaml
        ntfy.yaml                  # optional ExternalName placeholder
        keycloak-rpc-gateway.yaml  # optional
        networkpolicies.yaml
      bitcoin-net/
        bitcoind-regtest.yaml
        miner.yaml

  services/
    middleware/
      Dockerfile
      requirements.txt
      src/main.py
      config/example.env
    tx-builder/
      Dockerfile
      requirements.txt
      src/main.py
      config/example.env
    policy-signer/
      Dockerfile
      requirements.txt
      src/main.py
      config/example.env

  tools/
    proxmox/
      psbt_usbFlow
      README.md
    operator/
      usb-export-psbt.sh
      README.md
    cold/
      psbt-approve.sh
      hash-verify.sh
      README.md

  k8s/scripts/
    build-images.sh
    push-images.sh
    deploy.sh
```

***

## 3) Dependencies / Service Map (wer braucht wen)

### 3.1 Online Services (`btc-hot`)

#### `middleware` (HTTP API + Orchestration)

**Needs:**

*   `OPA_URL` → OPA decision calls
*   `NATS_URL` → publish/subscribe lifecycle events
*   `BITCOIND_RPC_URL` + `BITCOIND_RPC_USER/PASS` → broadcast via `sendrawtransaction`
*   `DATABASE_URL` → external Postgres
*   `NOTIFIER_URL` → ntfy endpoint (nur Schnittstelle, out-of-scope)
*   `policy-signer` → Hot auto-sign (HTTP)

**Calls:**

*   **OPA**: `POST /v1/data/policy/hot` und/oder `POST /v1/data/policy/refill`
*   **Policy‑Signer**: `POST /api/v1/sign`
*   **bitcoind (node-only)**: JSON-RPC `sendrawtransaction`
*   **Notifier (ntfy)**: `POST /notify/refill-needed` (placeholder contract)

***

#### `tx-builder` (Wallet‑Logik / PSBT Builder)

**Needs:**

*   `DATABASE_URL` (state, UTXO cache, intents)
*   `NATS_URL` (consume intents + publish results)
*   `OPA_URL` (refill-intent allow)
*   optional: bitcoind RPC read calls (fee estimates, mempool/chain info)
    *   `BITCOIND_RPC_URL` + creds

**Does:**

*   Builds **Refill PSBT** for cold->hot (transport as base64 via middleware endpoint)
*   Emits events:
    *   `intent.refill.created`
    *   `intent.refill.psbt_created`

***

#### `policy-signer` (Hot Key holder)

**Needs:**

*   `HOT_SIGNING_KEY` (placeholder; later HSM/KMS)
*   `OPA_URL` (optional: signer re-check / binding checks)
*   `DATABASE_URL` (optional: idempotency/audit)

**Called by:**

*   `middleware` only (NetworkPolicy blocks others)

**Endpoint:**

*   `POST /api/v1/sign` → returns `signed_rawtx_hex`

***

#### `opa` (Policy Engine)

**Needs:**

*   Policies (`policies/hot.rego`, `policies/refill.rego`, `policies/data.json`) mounted via ConfigMap (MVP)

**Called by:**

*   `middleware`
*   `policy-signer` (optional)
*   `tx-builder`

***

#### `nats` (Event bus)

**Needs:**

*   none (JetStream optional enabled)

***

### 3.2 Bitcoin Network Simulation (`btc-net`)

#### `bitcoind-regtest` (node-only)

**Needs:**

*   Persistent volume (chainstate)
*   RPC auth (Basic user/pass for Dev=Prod consistent)

**Exposes:**

*   RPC: `18443` (Cluster internal)
*   P2P: `18444` (optional)

#### `regtest-miner`

**Needs:**

*   bitcoind RPC creds
*   mines blocks to confirm TXs automatically (MVP: every 10s)

***

### 3.3 Offline / Air‑gapped VMs

#### Proxmox Host

*   `psbt_usbFlow` script:
    *   attaches/detaches `psbt-usb.qcow2` as `scsi2`
    *   waits for **ENTER** then detaches

#### Hot Operator VM

*   `usb-export-psbt.sh`:
    *   mounts USB
    *   fetches PSBT base64 from middleware
    *   writes `/mnt/usb/psbt/unappr.<id>.psbt`
    *   unmounts USB
    *   Operator presses **ENTER on Proxmox host**

#### Signer / KeyB / KeyC VMs

*   `psbt-approve.sh` (Signer): generates `approval.json` + `.sig` and `appr.<id>.psbt`, unmounts
*   `hash-verify.sh` (KeyB/KeyC): verifies approval + hash-binding, keeps USB mounted if OK (for Sparrow)

***

## 4) Data Formats / Contracts

### 4.1 Transport format: **Base64** for PSBT over HTTP/NATS

**Decision:**

*   PSBT is transported as **base64** in JSON payloads (robust for HTTP proxies + logs + NATS messages).
*   On USB it is stored as **binary `.psbt`** (Sparrow-friendly).

### 4.2 REST API Specs (OpenAPI)

*   `contracts/openapi/middleware.yaml`
    *   `GET /api/v1/intents/{id}/psbt?format=base64` → `{ psbt_base64 }`
    *   `POST /api/v1/hot/tx` → start hot tx flow
    *   `POST /api/v1/broadcast` → broadcast signed rawtx
*   `contracts/openapi/tx-builder.yaml`
    *   `POST /api/v1/build/refill-psbt`
*   `contracts/openapi/policy-signer.yaml`
    *   `POST /api/v1/sign`
*   `contracts/openapi/notifier.yaml`
    *   `POST /notify/refill-needed` (ntfy interface only)
*   `contracts/openapi/rpc-gateway.yaml`
    *   optional operator RPC gateway contract

### 4.3 Eventing Specs (AsyncAPI)

*   `contracts/asyncapi/nats.yaml` defines subjects:
    *   `intent.refill.created`
    *   `intent.refill.psbt_created`
    *   `tx.hot.requested`
    *   `tx.hot.approved`
    *   `tx.hot.signed`
    *   `tx.hot.broadcast`
    *   `tx.hot.confirmed`

***

## 5) Workflows (wer ruft wen wann)

### 5.1 Hot Auto‑Signing (extern, vollautomatisch)

1.  External system → `middleware: POST /api/v1/hot/tx`
2.  `middleware` → `OPA` allow check (`policy.hot`)
3.  `middleware` → `policy-signer: POST /api/v1/sign` (request\_id + tx\_hash binding)
4.  `middleware` → `bitcoind-regtest: sendrawtransaction`
5.  `middleware` publishes NATS lifecycle events

***

### 5.2 Cold Manual Refill (threshold -> intent -> human)

1.  `tx-builder` detects threshold breach (or receives balance event)
2.  `tx-builder` → `OPA` (`policy.refill`) checks allow\_intent + recommended\_amount
3.  `tx-builder` creates `intent.refill.created` (NATS)
4.  `tx-builder` builds PSBT and stores it under intent\_id
5.  `middleware` (or `tx-builder`) triggers **notify\_human** via Notifier interface (**ntfy out-of-scope**)

**Manual part (Operator + air‑gap):**

*   Operator exports PSBT to USB with `usb-export-psbt.sh`
*   Air‑gapped PSBT workflow executes offline signing

***

## 6) Manual Air‑gapped PSBT Workflow (Commands only)

> Voraussetzung: Signer Public Key ist einmalig verteilt (siehe `tools/cold/README.md`).

### 6.1 Export PSBT to USB (Hot Operator)

**Proxmox Host**

```bash
psbt_usbFlow hot
```

**Hot‑VM**

```bash
sudo API_BASE="http://middleware.btc-hot.svc.cluster.local:8080" \
     ./usb-export-psbt.sh <intent-id>
```

**Proxmox Host**

    ENTER

### 6.2 Approval (Signer)

**Proxmox Host**

```bash
psbt_usbFlow signer
```

**Signer‑VM**

```bash
sudo mount /dev/disk/by-label/USB /mnt/usb
sudo psbt-approve.sh
# unmount happens in script
```

**Proxmox Host**

    ENTER

### 6.3 Verify + BTC Sign (KeyB oder KeyC)

**Proxmox Host**

```bash
psbt_usbFlow keyb
```

**KeyB‑VM**

```bash
sudo mount /dev/disk/by-label/USB /mnt/usb
sudo hash-verify.sh
# USB stays mounted for Sparrow
# Sparrow: import appr.<id>.psbt, sign, export signed.<id>.psbt
sync
sudo umount /mnt/usb
```

**Proxmox Host**

    ENTER

### 6.4 Combine/Finalize (Signer) + Broadcast (Hot)

(analog zu euren bisherigen Runbooks)

***

## 7) Policy Setup (OPA)

### Files

*   `policies/hot.rego` → hot auto-sign allow/deny (whitelist, amount, velocity, network)
*   `policies/refill.rego` → refill intent allow + recommendation + notify flag
*   `policies/data.json` → limits, whitelists, allowed networks

### Deployment

OPA loads policies via ConfigMap in `deploy/k8s/base/opa.yaml`.

***

## 8. VolSync Backup Setup

### 8.1 Installation (einmalig)

```bash
helm repo add backube https://backube.github.io/helm-charts/
helm install -n volsync-system --create-namespace volsync backube/volsync
```

### 8.2 Backup konfigurieren

```bash
kubectl apply -f deploy/k8s/volsync/00-volsync-restic-secret.yaml
kubectl apply -f deploy/k8s/volsync/10-archive-replicationsource.yaml
```

✅ Backup ist **komplett entkoppelt**  
✅ Applikationen kennen das Backup‑Ziel nicht

***

## 9. Wiederherstellung (DR‑Gedanke)

*   Restore erfolgt über `ReplicationDestination`
*   Archiv‑PVC wird aus Backup wiederhergestellt
*   Middleware findet:
    *   PSBTs
    *   Broadcast‑Daten
    *   GPG‑Approvals

***

## 8) Deployment (Kubernetes/Talos)

### 8.1 Prereqs

*   `kubectl` configured to Talos cluster
*   external Postgres reachable (provide `DATABASE_URL`)
*   GHCR images available (public or configure `imagePullSecrets`)

### 8.2 Apply manifests

Recommended order (encoded in `k8s/scripts/deploy.sh`):

### 8.3 Verify

```bash
kubectl -n btc-hot get pods
kubectl -n btc-net get pods
kubectl -n btc-hot get svc
kubectl -n btc-net get svc
```

***

## 9) Build & Push Docker images

### 9.1 Build

```bash
export REG=ghcr.io/your-org
export TAG=0.1.0
bash k8s/scripts/build-images.sh
```

### 9.2 Push

```bash
export REG=ghcr.io/your-org
export TAG=0.1.0
bash k8s/scripts/push-images.sh
```

### 9.3 Deploy

```bash
bash k8s/scripts/deploy.sh
```

### 9.4 redploy on changes
```bash
export REG=ghcr.io/your-org
export TAG=0.1.0
bash k8s/scripts/build-images.sh
bash k8s/scripts/push-images.sh
kubectl -n btc-hot rollout restart deployment middleware
```

***

## 10) Service Configuration (example.env)

Each service has `config/example.env` as documentation of required env vars.  
In K8s, env vars are provided via:

*   `deploy/k8s/base/configmap.yaml` (non-secrets)
*   `deploy/k8s/base/secrets-template.yaml` (secrets)

***

## 11) Proxmox USB “Insert/Remove” Tooling

### Install (Proxmox Host)

*   Copy `tools/proxmox/psbt_usbFlow` to `/root/psbt-usb.sh` (or symlink)
*   Ensure executable:

```bash
chmod +x /root/psbt-usb.sh
```

### Usage

```bash
/root/psbt-usb.sh hot
/root/psbt-usb.sh signer
/root/psbt-usb.sh keyb
/root/psbt-usb.sh keyc
```

It will:

*   start VM if needed
*   attach usb qcow2 to `scsi2`
*   wait for ENTER
*   detach

***

## 12) Operator Tool (export PSBT to USB)

### Install (Hot Operator VM)

Copy `tools/operator/usb-export-psbt.sh` somewhere in `$PATH` and executable:

```bash
chmod +x usb-export-psbt.sh
```

### Usage

```bash
sudo API_BASE="http://middleware.btc-hot.svc.cluster.local:8080" \
     ./usb-export-psbt.sh <intent-id>
```

***

## 13) Notes / Next Implementation Steps (for future work)

This repo intentionally contains **skeleton services**:

*   `middleware` currently stubs PSBT retrieval (needs DB storage)
*   `tx-builder` stub: needs UTXO tracking, fee estimation, PSBT building
*   `policy-signer` stub: signing not implemented (placeholder `HOT_SIGNING_KEY`)

Planned next iterations:

*   DB schema (intents, tx lifecycle, audit, idempotency)
*   NATS JetStream stream/consumer definitions
*   Real PSBT build implementation (descriptor-based)
*   Real signing backend for policy-signer (HSM/KMS integration)
*   Notification integration with ntfy (external)

***

## PostGres-SQL DB

### 12.1 Minimaler DB‑Betrieb (How‑To)

**Migration ausführen (lokal/CI/CD):**

*   Variante A (einfach): `psql` direkt

```bash
psql "$DATABASE_URL" -f services/middleware/migrations/001_init.sql
```

*   Variante B (Job im Cluster):  
    Ein K8s Job, der `psql` nutzt und die Migration aus einem ConfigMap/Container ausführt (optional; sag Bescheid, dann schreibe ich dir den Job).

***

### 12.4 Mapping: Welche Aktion schreibt in welche Tabellen?

**Hot Auto‑Flow**

*   `intent` (type=hot\_tx)
*   `policy_decision` (policy.hot)
*   `hot_sign_request` (request\_id, tx\_hash, state)
*   `archived_tx` (nach Broadcast + Archivierung auf PVC)
*   optional `event_log` (NATS lifecycle)

**Cold Manual Refill**

*   `intent` (type=refill, state=WAITING\_HUMAN)
*   `policy_decision` (policy.refill)
*   `psbt_artifact` (stage=unappr/appr/signed/final, jeweils Pfad+Hash)
*   `archived_tx` (nach Broadcast + Archiv)
*   optional `event_log`

***














TEST
Deploy komplett grün (Pods Running, Services erreichbar)
DB Migrationen (001+002) im externen Postgres
Auto-build Pipeline testen (Intent event → Work‑PVC → Middleware GET returns base64)
Broadcast+Archive Pipeline testen (mit Dummy PSBT falls nötig, oder einfach Archive Endpoint via curl)
Observability:

/metrics in middleware/tx-builder/policy-signer
JSON logs in Loki


NetPol Verification:

“deny by default” wirklich wirksam?
nur erlaubte Egress/Ingress funktionieren