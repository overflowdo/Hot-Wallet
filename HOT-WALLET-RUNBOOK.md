# Hot Wallet Runbook

## 1) Ziel

Dieses Runbook beschreibt das Setup des `btc-hot` Hot-Wallet-Stacks, den Deploy-Prozess, die Schlüsselverwaltung in Bitwarden, das Laden von Transaktionen und die aktuell gültigen OPA-Policies.

## 2) Komponenten und Verantwortung

### 2.1 Online `btc-hot` Services

* `middleware` - HTTP-Orchestrierung für Hot-TX-Anfragen
* `policy-signer` - Signiert genehmigte PSBTs
* `tx-builder` - Erstellt Refill-Intents und PSBTs für den Cold-Flow
* `opa` - Policy-Entscheidungen für Hot- und Refill-Flows
* `nats` - Event-Bus für `tx-builder` und Lifecycle-Events

### 2.2 Bitcoin-Netzwerk

* `bitcoind-regtest` - regtest node-only Bitcoin Core
* `regtest-miner` - optionaler Miner für Blockbestätigungen

### 2.3 Secrets und Keys

* `HOT_SIGNING_KEY` - KMS KeyId oder Secret Identifier
* `HOT_SIGNING_PUBKEY` - zugehörige komprimierte Pubkey
* Beide Werte werden nicht direkt in ConfigMaps gespeichert, sondern über Bitwarden/ExternalSecret bezogen.

## 3) Voraussetzungen

* Kubernetes/Talos-Cluster mit Namespace `btc-hot` und `btc-net`
* Bitwarden-WebHook-Provider (`bitwarden-cli.secrets.svc.cluster.local`) verfügbar
* `external-secrets` installiert und ClusterSecretStore für Bitwarden konfiguriert
* Loki/Alloy Monitoring verfügbar für Log-Archivierung
* Zugriff auf Git-Repo und Deploy-Skripte

## 4) Setup der Hot-Wallet-Umgebung

### 4.1 Bitwarden Secret Store

Die Hot-Wallet-Schlüssel werden über `k8s/apps/btc-hot/common/external-secret.yaml` bezogen.

Beispiel:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: btc-hot-signing-keys
  namespace: btc-hot
spec:
  refreshInterval: 15s
  secretStoreRef:
    name: bitwarden-login
    kind: ClusterSecretStore
  target:
    name: btc-hot-signing-keys
    creationPolicy: Owner
  data:
  - secretKey: HOT_SIGNING_KEY
    remoteRef:
      key: btc-hot-signing-key-id
      property: password
  - secretKey: HOT_SIGNING_PUBKEY
    remoteRef:
      key: btc-hot-signing-pubkey
      property: username
```

Passe `btc-hot-signing-key-id` und `btc-hot-signing-pubkey` an die tatsächlichen Bitwarden-Items an.

### 4.2 ConfigMap / Secret Deployment

* `k8s/apps/btc-hot/common/configmap.yaml` enthält allgemeine URLs und Endpoints
* `k8s/apps/btc-hot/common/secrets.yaml` enthält Datenbank- und Bitcoin-RPC-Zugang
* `k8s/apps/btc-hot/common/external-secret.yaml` wird in `k8s/apps/btc-hot/common/kustomization.yaml` eingebunden

SIMULATE_SIGNING=true für simulation
SIGNER_BACKEND=soft umstellen 

### 4.3 Policy Signer Deployment

`k8s/apps/btc-hot/policy-signer/app/policy-signer.yaml` referenziert `btc-hot-signing-keys` statt eines hard-codierten Secrets.

## 5) Deployment Ablauf

### 5.1 Vorbereitung

1. Prüfe, dass die Namespace- und Base-Ressourcen verfügbar sind.
2. Stelle sicher, dass `bitwarden-cli` WebHook erreichbar ist.
3. Stelle sicher, dass Loki/Alloy in der Monitoring-Umgebung läuft.

### 5.2 Automatisches Deployment mit Skript

```bash
cd deploy/scripts
bash deploy.sh
```

Das Skript wendet die Base-Ressourcen, Core-Services und Hot-Services in der richtigen Reihenfolge an.

### 5.3 Docker Image Build / Push

Falls du eigene Images bauen und in ein Registry pushen möchtest, nutze:

```bash
cd deploy/scripts
bash build-images.sh
bash push-images.sh
```

* `build-images.sh` baut die Container-Images für `middleware`, `tx-builder` und `policy-signer`.
* `push-images.sh` pusht diese Images in die Registry, damit Kubernetes sie ziehen kann.

### 5.4 Optional: Bitcoin-Regtest deployen

```bash
cd k8s/apps/bitcoin-net
kubectl apply -f bitcoind-regtest.yaml
kubectl apply -f miner.yaml
```

### 5.4 Optional: Bitcoin-Regtest deployen

```bash
cd k8s/apps/bitcoin-net
kubectl apply -f bitcoind-regtest.yaml
kubectl apply -f miner.yaml
```

### 5.5 Deployment Tasks

* Prüfe, dass das ExternalSecret `btc-hot-signing-keys` erzeugt wurde:
  * `kubectl get secret btc-hot-signing-keys -n btc-hot`
* Prüfe die bereitgestellten PVCs:
  * `kubectl get pvc -n btc-hot`
* Überwache den Rollout der Deployments:
  * `kubectl rollout status deployment/nats -n btc-hot`
  * `kubectl rollout status deployment/opa -n btc-hot`
  * `kubectl rollout status deployment/middleware -n btc-hot`
  * `kubectl rollout status deployment/tx-builder -n btc-hot`
  * `kubectl rollout status deployment/policy-signer -n btc-hot`
* Validere das `ntfy`-Fallbackszenario:
  * `NOTIFIER_URL` muss auf eine erreichbare ntfy-Instanz zeigen
  * Teste die Notification-Route: `POST /notify/refill-needed`
* Prüfe, dass die `policy-signer` Umgebungsvariablen aus `btc-hot-signing-keys` geladen werden.
* Prüfe `middleware`-Logs auf erfolgreiche OPA- und PSBT-Flows.

### 5.4 Überprüfen

* `kubectl get pods -n btc-hot`
* `kubectl get secrets -n btc-hot | grep btc-hot-signing-keys`
* `kubectl logs -n btc-hot policy-signer-...`

## 6) Hot Wallet Initialisierung

### 6.1 Keys erstellen / Provisionieren

1. Erzeuge AWS KMS Key (oder HSM-Key) für den Hot-Signer.
2. Erfasse die zugehörige komprimierte Pubkey.
3. Speichere:
   * `HOT_SIGNING_KEY` als KeyId/alias
   * `HOT_SIGNING_PUBKEY` als komprimierte Pubkey
4. Verifiziere, dass ExternalSecret das Secret erfolgreich erstellt.

### 6.2 Key Rotation / Aktualisierung

* Aktualisiere Bitwarden-Eintrag
* ExternalSecret synchronisiert den Wert automatisch
* Starte `policy-signer` neu, falls nötig

## 7) Transaktion Laden und Signieren

### 7.1 Hot-Flow (PSBT)

1. Externes System sendet `POST /api/v1/hot/tx` an `middleware`
2. `middleware` baut PSBT oder nimmt vorhandene `unsigned_psbt_base64`
3. `middleware` fragt `opa` an: `policy.hot`
4. Ist die Policy erlaubt, schickt `middleware` die PSBT an `policy-signer`
5. `policy-signer` prüft OPA erneut und signiert dann PSBT
6. `middleware` extrahiert die finale Raw-TX aus `signed_psbt_base64`
7. `middleware` sendet `sendrawtransaction` an `bitcoind-regtest`

### 7.2 Cold-Refill-Flow

1. `tx-builder` detektiert Füllstands- oder Threshold-Break
2. `tx-builder` fragt `opa` für `policy.refill`
3. Bei Erlaubnis erstellt `tx-builder` einen Refill-Intent und `intent.refill.created`
4. PSBT wird aufgebaut und als `base64` persistiert
5. Operator exportiert PSBT auf USB und führt Air-gapped Workflow aus

## 8) Aktuelle Policies

### 8.1 `policy.hot`

* Whitelist von erlaubten Zieladressen
* Maximaler Betrag pro Transaktion
* Netzwerk- und Velocity-Beschränkungen
* `tx_hash` / `request_id` Binding zur Idempotenz

### 8.2 `policy.refill`

* Erlaubt Refill-Intents nur bei positivem Monitoring-Status
* Berechnet empfohlene Refill-Menge
* Ergänzt `notify_human` / `notify_operator` Flags

### 8.3 `policies/data.json`

Enthält:

* Limits und Schwellenwerte
* erlaubte Netzwerke
* Whitelists für Empfänger-Identitäten

## 9) Logging und Monitoring

* `Loki` / `Alloy` ist als Log-Pipeline im Monitoring-Stack.
* Die `alloy`-Konfiguration überwacht Kubernetes-Pod-Logs und leitet sie an Loki weiter.
* Prüfe, ob die `btc-hot` Pods im Loki-Dashboard auftauchen.

## 10) Verifizierungs- und Deployment-Tasks

### 10.1 Service- und Secret-Validierung

* Prüfe, dass das ExternalSecret `btc-hot-signing-keys` vorhanden ist und die Secrets korrekt erzeugt wurden:
  * `kubectl get secret btc-hot-signing-keys -n btc-hot`
  * `kubectl describe secret btc-hot-signing-keys -n btc-hot`
* Validere, dass `policy-signer` die benötigten Umgebungsvariablen lädt:
  * `kubectl exec -n btc-hot deploy/policy-signer -- printenv | grep HOT_SIGNING`
* Prüfe, dass `NOTIFIER_URL` erreichbar ist und `POST /notify/refill-needed` simuliert werden kann.

### 10.2 Workflow-Tests

* Teste den Hot-Flow komplett in der regtest-Umgebung:
  1. `POST /api/v1/hot/tx` an `middleware`
  2. prüfe OPA-Entscheidung (`policy.hot`)
  3. bestätige, dass `policy-signer` die PSBT signiert und `middleware` broadcastet
* Teste den Cold-Refill-Flow:
  1. Trigger einen Refill-Intent im `tx-builder`
  2. prüfe NATS-Event `intent.refill.created`
  3. verifiziere, dass ein PSBT erstellt wird und per USB-Export weitergegeben werden kann

### 10.3 Monitoring-Prüfung

* Stelle sicher, dass `btc-hot` Logs in Loki ankommen:
  * Suche nach `middleware`, `tx-builder`, `policy-signer` und `opa` in Grafana/Loki
* Prüfe, ob Alloy die Pod-Logs korrekt relabelt und weiterleitet.

### 10.4 Produktionsvorbereitende Aufgaben

* Validere den KMS/HSM-Signaturpfad im `policy-signer` mit echtem Key-Backend.
* Verifiziere die Bitwarden-Item-IDs und das Secret-Mapping im Cluster.
* Ergänze `tx-builder` um robustes UTXO-Tracking und Fee-Estimation, bevor du in eine produktive Umgebung gehst.
* Prüfe, ob NATS für den `tx-builder` Lifecycle-Flow sauber läuft und ob JetStream-Streams / Konsumenten definiert sind.

### 10.5 Deployment Tasks (falls Schritte automatisiert werden sollen)

* Erstelle ein Deployment-Playbook oder ein Makefile für:
  * `k8s/apps/btc-hot/common/kustomization.yaml`
  * `k8s/apps/btc-hot/nats/app/kustomization.yaml`
  * `k8s/apps/btc-hot/opa/app/kustomization.yaml`
  * `k8s/apps/btc-hot/middleware/app/kustomization.yaml`
  * `k8s/apps/btc-hot/tx-builder/app/kustomization.yaml`
  * `k8s/apps/btc-hot/policy-signer/app/policy-signer.yaml`
* Ergänze Automatisierung für das Provisionieren der Bitwarden-Secrets und den Rollout des `policy-signer`.
