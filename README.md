# RabbitMQ on k3s with SSL/TLS Deployment Guide

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Certificate Preparation](#certificate-preparation)
3. [RabbitMQ Deployment on k3s](#rabbitmq-deployment-on-k3s)
4. [SSL/TLS Configuration](#ssltls-configuration)
5. [Load Balancer Configuration](#load-balancer-configuration)
6. [Management Plugin Configuration](#management-plugin-configuration)
7. [PKCS12 Certificate Format](#pkcs12-certificate-format)
8. [Certificate Import to Keystore for Containerized Applications](#certificate-import-to-keystore-for-containerized-applications)
9. [Application Configuration for k3s Containers](#application-configuration-for-k3s-containers)
10. [Testing and Verification](#testing-and-verification)
11. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- k3s cluster up and running
- kubectl configured to access your k3s cluster
- Certificates: `tls.crt` and `tls.key`
- DNS name configured for RabbitMQ service
- Access to create Kubernetes secrets, services, and deployments

---

## Certificate Preparation

### Step 1: Verify Your Certificates

Ensure you have:
- `tls.crt` - Certificate file (PEM format)
- `tls.key` - Private key file (PEM format)

```bash
# Verify certificate
openssl x509 -in tls.crt -text -noout

# Verify private key
openssl rsa -in tls.key -check
```

### Step 2: Prepare Certificate for RabbitMQ

RabbitMQ requires the certificate and key in a specific format. If needed, combine them:

```bash
# Create a combined certificate file (if needed)
cat tls.crt tls.key > rabbitmq-combined.pem
```

### Step 3: Create Client Certificates from Server Certificates

For client applications that need to authenticate to RabbitMQ using mutual TLS (mTLS), you have two options:

#### Option A: Use the Same Certificate for Client (Simpler, for Development/Testing)

If you want to use the same certificate for both server and client (useful for development/testing):

```bash
# Copy server certificate and key as client certificate
cp tls.crt client.crt
cp tls.key client.key

# Verify client certificate
openssl x509 -in client.crt -text -noout
```

**Note**: Using the same certificate for server and client is not recommended for production environments. Use Option B for production.

#### Option B: Create Separate Client Certificates (Recommended for Production)

If you have a Certificate Authority (CA) that signed your server certificate, create separate client certificates:

**Step 3.1: Extract CA Certificate (if needed)**

If your `tls.crt` contains a certificate chain, extract the CA certificate:

```bash
# Extract CA certificate from certificate chain
openssl x509 -in tls.crt -text -noout | grep -A 10 "Issuer:"
# Or if you have a separate CA certificate file, use that
```

**Step 3.2: Generate Client Private Key**

```bash
# Generate a new private key for the client
openssl genrsa -out client.key 2048

# Verify the key
openssl rsa -in client.key -check
```

**Step 3.3: Create Client Certificate Signing Request (CSR)**

```bash
# Create a certificate signing request for the client
openssl req -new -key client.key -out client.csr -subj "/CN=rabbitmq-client/O=Client"

# Or create CSR with a config file for more options
cat > client.conf <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
CN = rabbitmq-client
O = Client

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = clientAuth
EOF

openssl req -new -key client.key -out client.csr -config client.conf
```

**Step 3.4: Sign Client Certificate with CA**

If you have access to your CA:

```bash
# Sign the client certificate with your CA
openssl x509 -req -in client.csr \
  -CA ca.crt \
  -CAkey ca.key \
  -CAcreateserial \
  -out client.crt \
  -days 365 \
  -extensions v3_req \
  -extfile client.conf

# Verify the client certificate
openssl x509 -in client.crt -text -noout
```

**Step 3.5: Alternative - Self-Signed Client Certificate (for Testing)**

If you don't have a CA, create a self-signed client certificate:

```bash
# Create self-signed client certificate
openssl req -new -x509 -key client.key -out client.crt -days 365 \
  -subj "/CN=rabbitmq-client/O=Client" \
  -extensions v3_req \
  -config <(cat <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
CN = rabbitmq-client
O = Client

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = clientAuth
EOF
)

# Verify the self-signed client certificate
openssl x509 -in client.crt -text -noout
```

**Step 3.6: Verify Client Certificate**

```bash
# Check client certificate details
openssl x509 -in client.crt -text -noout

# Verify certificate and key match
openssl x509 -noout -modulus -in client.crt | openssl md5
openssl rsa -noout -modulus -in client.key | openssl md5
# Both should output the same MD5 hash
```

**Step 3.7: Create Client Certificate in PKCS12 Format**

For Java applications, convert client certificate to PKCS12:

```bash
# Create PKCS12 from client certificate and key
openssl pkcs12 -export \
  -in client.crt \
  -inkey client.key \
  -out client.p12 \
  -name rabbitmq-client \
  -password pass:changeit

# If you have a CA certificate, include it in the PKCS12
openssl pkcs12 -export \
  -in client.crt \
  -inkey client.key \
  -certfile ca.crt \
  -out client-with-ca.p12 \
  -name rabbitmq-client \
  -password pass:changeit

# Verify PKCS12 file
openssl pkcs12 -info -in client.p12 -passin pass:changeit -noout
```

**Important Notes:**
- **For Development/Testing**: Option A (using the same certificate) is simpler and sufficient
- **For Production**: Use Option B to create separate client certificates with proper CA signing
- Client certificates should have `extendedKeyUsage = clientAuth` extension
- Store client certificates securely and never share private keys
- Each client application should ideally have its own unique client certificate

---

## RabbitMQ Deployment on k3s

### Step 1: Create Kubernetes Secret for Certificates

```bash
# Create namespace (if not exists)
kubectl create namespace rabbitmq

# Create secret with TLS certificates
kubectl create secret tls rabbitmq-tls \
  --cert=tls.crt \
  --key=tls.key \
  --namespace=rabbitmq
```

### Step 2: Create RabbitMQ Configuration ConfigMap

Create a file `rabbitmq.conf`:

```ini
# Enable both SSL and non-SSL listeners
listeners.tcp.default = 5672
listeners.ssl.default = 5671

# SSL Configuration
ssl_options.cacertfile = /etc/rabbitmq/ssl/tls.crt
ssl_options.certfile = /etc/rabbitmq/ssl/tls.crt
ssl_options.keyfile = /etc/rabbitmq/ssl/tls.key
ssl_options.verify = verify_none
ssl_options.fail_if_no_peer_cert = false

# Management Plugin Configuration
# Enable management plugin (required for web UI)
management.ssl.port = 8443
management.ssl.cacertfile = /etc/rabbitmq/ssl/tls.crt
management.ssl.certfile = /etc/rabbitmq/ssl/tls.crt
management.ssl.keyfile = /etc/rabbitmq/ssl/tls.key
# Optional: Enable non-SSL management port (not recommended for production)
# management.tcp.port = 15672
```

Create the ConfigMap:

```bash
kubectl create configmap rabbitmq-config \
  --from-file=rabbitmq.conf \
  --namespace=rabbitmq
```

### Step 2.5: Create Enabled Plugins ConfigMap (Optional - Alternative Approach)

**Note**: This step is optional. The deployment in Step 3 uses an init container approach which is recommended. However, if you prefer to use a ConfigMap instead, follow this step and modify the deployment accordingly.

Create a file `enabled_plugins` with the following content:

```
[rabbitmq_management,rabbitmq_management_agent].
```

**Important**: The file must end with a period (`.`) and use Erlang list syntax. This file tells RabbitMQ which plugins to enable at startup.

Create the ConfigMap:

```bash
kubectl create configmap rabbitmq-enabled-plugins \
  --from-file=enabled_plugins \
  --namespace=rabbitmq
```

### Step 3: Create RabbitMQ Deployment

**Note**: This deployment uses an init container to automatically create the `enabled_plugins` file, so Step 2.5 (ConfigMap) is optional. The init container approach is more reliable for handling read-only filesystem issues.

Create a file `rabbitmq-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rabbitmq
  namespace: rabbitmq
  labels:
    app: rabbitmq
spec:
  replicas: 1
  selector:
    matchLabels:
      app: rabbitmq
  template:
    metadata:
      labels:
        app: rabbitmq
    spec:
      initContainers:
      - name: setup-config
        image: busybox:latest
        command: ['sh', '-c']
        args:
        - |
          # Copy rabbitmq.conf from config source
          cp /config-source/rabbitmq.conf /rabbitmq-config/rabbitmq.conf
          # Create enabled_plugins file
          echo '[rabbitmq_management,rabbitmq_management_agent].' > /rabbitmq-config/enabled_plugins
          # Create ssl directory and copy TLS certificates
          mkdir -p /rabbitmq-config/ssl
          cp /tls-source/tls.crt /rabbitmq-config/ssl/tls.crt
          cp /tls-source/tls.key /rabbitmq-config/ssl/tls.key
          echo "Configuration files prepared successfully"
          ls -la /rabbitmq-config/
          ls -la /rabbitmq-config/ssl/
          cat /rabbitmq-config/enabled_plugins
        volumeMounts:
        - name: rabbitmq-config-source
          mountPath: /config-source
          readOnly: true
        - name: tls-source
          mountPath: /tls-source
          readOnly: true
        - name: rabbitmq-config
          mountPath: /rabbitmq-config
      containers:
      - name: rabbitmq
        image: rabbitmq:3.12-management-alpine
        ports:
        - containerPort: 5672
          name: amqp
        - containerPort: 5671
          name: amqps
        - containerPort: 8443
          name: management-ssl
        - containerPort: 15672
          name: management
        env:
        - name: RABBITMQ_DEFAULT_USER
          value: "admin"
        - name: RABBITMQ_DEFAULT_PASS
          valueFrom:
            secretKeyRef:
              name: rabbitmq-credentials
              key: password
        volumeMounts:
        # Mount the writable config directory (prepared by init container)
        # This includes rabbitmq.conf, enabled_plugins, and ssl/ directory
        - name: rabbitmq-config
          mountPath: /etc/rabbitmq
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2000m"
      volumes:
      # Source ConfigMap for rabbitmq.conf (read-only, copied by init container)
      - name: rabbitmq-config-source
        configMap:
          name: rabbitmq-config
      # Source Secret for TLS certificates (read-only, copied by init container)
      - name: tls-source
        secret:
          secretName: rabbitmq-tls
      # Writable volume for all RabbitMQ config files (prepared by init container)
      # This includes: rabbitmq.conf, enabled_plugins, and ssl/ directory with certificates
      # This avoids read-only filesystem issues
      - name: rabbitmq-config
        emptyDir: {}
---
apiVersion: v1
kind: Secret
metadata:
  name: rabbitmq-credentials
  namespace: rabbitmq
type: Opaque
stringData:
  password: "your-secure-password-here"
```

Deploy RabbitMQ:

```bash
kubectl apply -f rabbitmq-deployment.yaml
```

**Note**: This deployment includes:
- **Init Container Approach**: An init container (`setup-config`) prepares all configuration files in a writable `emptyDir` volume:
  - Copies `rabbitmq.conf` from ConfigMap
  - Creates `enabled_plugins` file to enable management plugins
  - Copies TLS certificates from Secret to `ssl/` directory
  - This approach avoids read-only filesystem issues by using a writable volume
- **Management Plugin Configuration**: The `enabled_plugins` file automatically enables `rabbitmq_management` and `rabbitmq_management_agent` plugins at startup.
- **SSL/TLS Support**: Certificates are copied from the `rabbitmq-tls` secret to the config directory.
- **Management UI**: Configured to listen on port 8443 (HTTPS) as specified in `rabbitmq.conf`.

After deployment, verify the management plugin is enabled:

```bash
# Wait for pod to be ready
kubectl wait --for=condition=ready pod -l app=rabbitmq -n rabbitmq --timeout=120s

# Check init container logs to verify configuration was prepared
kubectl logs deployment/rabbitmq -n rabbitmq -c setup-config

# Verify enabled_plugins file exists and has correct content
kubectl exec -it deployment/rabbitmq -n rabbitmq -- cat /etc/rabbitmq/enabled_plugins

# Expected output should show:
# [rabbitmq_management,rabbitmq_management_agent].

# Verify TLS certificates are in place
kubectl exec -it deployment/rabbitmq -n rabbitmq -- ls -la /etc/rabbitmq/ssl/

# Verify management plugin is enabled
kubectl exec -it deployment/rabbitmq -n rabbitmq -- rabbitmq-plugins list | grep management

# Expected output (should show [E*] for enabled and running):
# [E*] rabbitmq_management               3.12.14
# [E*] rabbitmq_management_agent         3.12.14
```

### Step 4: Create RabbitMQ Service

Create a file `rabbitmq-service.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: rabbitmq
  namespace: rabbitmq
  labels:
    app: rabbitmq
spec:
  type: ClusterIP
  ports:
  - port: 5672
    targetPort: 5672
    protocol: TCP
    name: amqp
  - port: 5671
    targetPort: 5671
    protocol: TCP
    name: amqps
  - port: 8443
    targetPort: 8443
    protocol: TCP
    name: management-ssl
  - port: 15672
    targetPort: 15672
    protocol: TCP
    name: management
  selector:
    app: rabbitmq
```

Apply the service:

```bash
kubectl apply -f rabbitmq-service.yaml
```

---

## SSL/TLS Configuration

### Step 1: Verify RabbitMQ SSL Configuration

```bash
# Check RabbitMQ logs
kubectl logs -f deployment/rabbitmq -n rabbitmq

# Look for SSL listener startup messages:
# "started SSL listener on [::]:5671"
```

### Step 2: Test SSL Connection

```bash
# Port forward to test locally
kubectl port-forward -n rabbitmq service/rabbitmq 5671:5671

# In another terminal, test SSL connection
openssl s_client -connect localhost:5671 -cert tls.crt -key tls.key
```

---

## Load Balancer Configuration

### Step 1: Create LoadBalancer Service for SSL Port

Create a file `rabbitmq-lb.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: rabbitmq-ssl-lb
  namespace: rabbitmq
  labels:
    app: rabbitmq
spec:
  type: LoadBalancer
  ports:
  - port: 443
    targetPort: 5671
    protocol: TCP
    name: amqps
  selector:
    app: rabbitmq
```

Apply the LoadBalancer:

```bash
kubectl apply -f rabbitmq-lb.yaml
```

### Step 2: Get LoadBalancer IP/Endpoint

```bash
# Get the external IP or hostname
kubectl get svc rabbitmq-ssl-lb -n rabbitmq

# Example output:
# NAME              TYPE           CLUSTER-IP     EXTERNAL-IP      PORT(S)        AGE
# rabbitmq-ssl-lb   LoadBalancer   10.43.x.x     192.168.1.100    443:31234/TCP  5m
```

### Step 3: Configure DNS

Point your DNS name to the LoadBalancer external IP:

```bash
# Example: rabbitmq.example.com -> 192.168.1.100
# Update your DNS records accordingly
```

---

## Management Plugin Configuration

The RabbitMQ Management Plugin provides a web-based UI for monitoring and managing your RabbitMQ server. This section covers accessing the management UI securely on port 8443 via HTTPS.

### Step 1: Management Plugin Status

The management plugin is automatically enabled in the deployment via an init container (`setup-config`) that prepares all configuration files in a writable volume (see Step 3 deployment YAML). The init container creates the `enabled_plugins` file before RabbitMQ starts, enabling `rabbitmq_management` and `rabbitmq_management_agent` plugins automatically.

**Note**: In containerized environments, `/etc/rabbitmq` cannot be written to directly when mounted from ConfigMaps/Secrets. The deployment uses an init container with a writable `emptyDir` volume to prepare all configuration files (including `enabled_plugins`), which is then mounted to `/etc/rabbitmq`. This is the recommended approach.

Verify the plugin is enabled:

```bash
# Check if plugin is enabled (should show [E*] for enabled and running)
kubectl exec -it deployment/rabbitmq -n rabbitmq -- rabbitmq-plugins list | grep management

# Expected output:
# [E*] rabbitmq_management               3.12.14
# [E*] rabbitmq_management_agent         3.12.14

# Check RabbitMQ logs for management plugin startup
kubectl logs deployment/rabbitmq -n rabbitmq | grep -i management
```

### Step 2: Verify Management Plugin Configuration

Check that the management plugin is configured correctly in RabbitMQ:

```bash
# Check RabbitMQ logs for management plugin startup
kubectl logs deployment/rabbitmq -n rabbitmq | grep -i management

# You should see messages like:
# "Management plugin started. Port: 8443"
```

### Step 3: Create LoadBalancer Service for Management UI (Port 8443)

Create a LoadBalancer service to expose the management UI on port 8443:

Create a file `rabbitmq-management-lb.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: rabbitmq-management-lb
  namespace: rabbitmq
  labels:
    app: rabbitmq
    component: management
spec:
  type: LoadBalancer
  ports:
  - port: 8443
    targetPort: 8443
    protocol: TCP
    name: management-https
  selector:
    app: rabbitmq
```

Apply the LoadBalancer:

```bash
kubectl apply -f rabbitmq-management-lb.yaml
```

### Step 4: Get Management UI LoadBalancer Endpoint

```bash
# Get the external IP or hostname for management UI
kubectl get svc rabbitmq-management-lb -n rabbitmq

# Example output:
# NAME                    TYPE           CLUSTER-IP     EXTERNAL-IP      PORT(S)          AGE
# rabbitmq-management-lb   LoadBalancer   10.43.x.x     192.168.1.101    8443:31235/TCP   2m
```

### Step 5: Configure DNS for Management UI (Optional)

You can create a separate DNS entry for the management UI:

```bash
# Example: rabbitmq-mgmt.example.com -> 192.168.1.101
# Or use the same domain with a different subdomain
# management.rabbitmq.example.com -> 192.168.1.101
```

### Step 6: Access Management UI

#### Access via LoadBalancer IP

1. Open your web browser
2. Navigate to: `https://<LOADBALANCER-IP>:8443`
   - Example: `https://192.168.1.101:8443`
3. Accept the SSL certificate warning (if using self-signed certificates)
4. Login with credentials:
   - **Username**: `admin` (or your configured username)
   - **Password**: `your-secure-password-here` (from your secret)

#### Access via DNS Name

If you configured DNS:

1. Navigate to: `https://rabbitmq-mgmt.example.com:8443`
   - Or: `https://management.rabbitmq.example.com:8443`
2. Login with your credentials

#### Access via Port Forward (for testing)

For local testing without LoadBalancer:

```bash
# Port forward management UI
kubectl port-forward -n rabbitmq service/rabbitmq 8443:8443

# Then access in browser:
# https://localhost:8443
```

### Step 7: Verify Management Plugin Features

Once logged in, you should be able to access:

- **Overview**: Server and cluster information
- **Connections**: Active client connections
- **Channels**: Open channels
- **Exchanges**: Message exchanges
- **Queues**: Message queues
- **Admin**: User and virtual host management
- **Monitoring**: Metrics and statistics

### Step 8: Management Plugin API Access

The management plugin also provides a REST API. You can access it via HTTPS:

```bash
# Get cluster overview via API
curl -k -u admin:your-secure-password-here \
  https://rabbitmq-mgmt.example.com:8443/api/overview

# List all queues
curl -k -u admin:your-secure-password-here \
  https://rabbitmq-mgmt.example.com:8443/api/queues

# Get node information
curl -k -u admin:your-secure-password-here \
  https://rabbitmq-mgmt.example.com:8443/api/nodes
```

**Note**: The `-k` flag skips SSL certificate verification. In production, use proper certificate validation.

### Step 9: Secure Management Plugin Access (Best Practices)

1. **Use Strong Passwords**: Ensure RabbitMQ admin user has a strong password
2. **Restrict Network Access**: Use NetworkPolicies to restrict access to management port
3. **Enable Authentication**: Management UI requires authentication by default
4. **Use HTTPS Only**: Disable non-SSL management port in production
5. **Monitor Access**: Regularly check management UI access logs
6. **Certificate Validation**: Use properly signed certificates in production

### Step 10: Troubleshooting Management Plugin

#### Issue: Cannot enable plugin - Read-only filesystem error

**Error**: `{:cannot_write_enabled_plugins_file, ~c"/etc/rabbitmq/enabled_plugins", :erofs}`

This error occurs because `/etc/rabbitmq` is mounted as read-only in the container. You cannot use `rabbitmq-plugins enable` command directly.

**Solution**: The deployment uses an init container (`setup-config`) to prepare all configuration files including `enabled_plugins` (see Step 3 in RabbitMQ Deployment section). If you're seeing this error, check:

1. **Verify init container completed successfully**:
```bash
# Check init container logs
kubectl logs deployment/rabbitmq -n rabbitmq -c setup-config

# Check if enabled_plugins file exists in the pod
kubectl exec -it deployment/rabbitmq -n rabbitmq -- cat /etc/rabbitmq/enabled_plugins

# Verify all config files are present
kubectl exec -it deployment/rabbitmq -n rabbitmq -- ls -la /etc/rabbitmq/
```

2. **If the file doesn't exist, restart the deployment**:
```bash
# Restart the deployment to re-run init container
kubectl rollout restart deployment/rabbitmq -n rabbitmq

# Wait for pod to be ready
kubectl wait --for=condition=ready pod -l app=rabbitmq -n rabbitmq --timeout=120s

# Verify plugin is enabled
kubectl exec -it deployment/rabbitmq -n rabbitmq -- rabbitmq-plugins list | grep management
```

3. **If init container is failing, check the deployment YAML**:
   - Ensure the `rabbitmq-config` emptyDir volume is defined
   - Ensure the init container `setup-config` is present
   - Ensure the source volumes (`rabbitmq-config-source` and `tls-source`) are correctly defined
   - Check init container logs for specific errors: `kubectl logs deployment/rabbitmq -n rabbitmq -c setup-config`

#### Issue: Management UI not accessible

```bash
# Check if plugin is enabled
kubectl exec -it deployment/rabbitmq -n rabbitmq -- rabbitmq-plugins list | grep management

# Expected output should show [E*] for enabled and running:
# [E*] rabbitmq_management               3.12.14
# [E*] rabbitmq_management_agent         3.12.14

# Check RabbitMQ logs
kubectl logs deployment/rabbitmq -n rabbitmq | grep -i "management\|8443"

# Verify service is running
kubectl get svc rabbitmq-management-lb -n rabbitmq

# Check pod status
kubectl get pods -n rabbitmq -l app=rabbitmq

# Verify enabled_plugins file exists and is correct
kubectl exec -it deployment/rabbitmq -n rabbitmq -- cat /etc/rabbitmq/enabled_plugins
```

#### Issue: SSL certificate errors

```bash
# Verify certificates are mounted correctly
kubectl exec -it deployment/rabbitmq -n rabbitmq -- ls -la /etc/rabbitmq/ssl/

# Check certificate validity
kubectl exec -it deployment/rabbitmq -n rabbitmq -- openssl x509 -in /etc/rabbitmq/ssl/tls.crt -text -noout
```

#### Issue: Cannot login to management UI

```bash
# Verify credentials
kubectl get secret rabbitmq-credentials -n rabbitmq -o jsonpath='{.data.password}' | base64 -d

# Reset password if needed (exec into pod)
kubectl exec -it deployment/rabbitmq -n rabbitmq -- rabbitmqctl change_password admin new-password
```

---

## PKCS12 Certificate Format

PKCS12 (also known as .p12 or .pfx) is a binary format for storing certificates and private keys. It's widely used in Java applications and provides a secure way to bundle certificates with their private keys.

### Step 1: Create PKCS12 from Existing Certificates

If you have `tls.crt` and `tls.key` files, convert them to PKCS12 format:

```bash
# Create PKCS12 file from certificate and private key
openssl pkcs12 -export \
  -in tls.crt \
  -inkey tls.key \
  -out rabbitmq-server.p12 \
  -name rabbitmq-server \
  -password pass:changeit

# Verify the PKCS12 file was created
ls -lh rabbitmq-server.p12
```

**Note**: Replace `changeit` with a strong password in production environments.

### Step 2: Create PKCS12 with Certificate Chain

If you have intermediate certificates or a certificate chain:

```bash
# Create PKCS12 with full certificate chain
openssl pkcs12 -export \
  -in tls.crt \
  -inkey tls.key \
  -certfile intermediate.crt \
  -out rabbitmq-server-chain.p12 \
  -name rabbitmq-server \
  -password pass:changeit
```

### Step 3: Verify PKCS12 File Contents

```bash
# View PKCS12 file information (will prompt for password)
openssl pkcs12 -info \
  -in rabbitmq-server.p12 \
  -passin pass:changeit \
  -noout

# List certificates in PKCS12 file
openssl pkcs12 -info \
  -in rabbitmq-server.p12 \
  -passin pass:changeit \
  -nodes \
  -nokeys

# Extract certificate from PKCS12 (for verification)
openssl pkcs12 -in rabbitmq-server.p12 \
  -passin pass:changeit \
  -clcerts \
  -nokeys \
  -out extracted-cert.pem

# Extract private key from PKCS12
openssl pkcs12 -in rabbitmq-server.p12 \
  -passin pass:changeit \
  -nocerts \
  -nodes \
  -out extracted-key.pem
```

### Step 4: Convert PKCS12 to JKS Format

Java applications often require JKS format. Convert PKCS12 to JKS:

```bash
# Convert PKCS12 to JKS
keytool -importkeystore \
  -srckeystore rabbitmq-server.p12 \
  -srcstoretype PKCS12 \
  -srcstorepass changeit \
  -destkeystore rabbitmq-server.jks \
  -deststoretype JKS \
  -deststorepass changeit \
  -destkeypass changeit \
  -noprompt

# Verify JKS file
keytool -list -v -keystore rabbitmq-server.jks -storepass changeit
```

### Step 5: Import PKCS12 into Existing JKS Keystore

If you already have a JKS keystore and want to add the PKCS12 certificate:

```bash
# Import PKCS12 into existing JKS keystore
keytool -importkeystore \
  -srckeystore rabbitmq-server.p12 \
  -srcstoretype PKCS12 \
  -srcstorepass changeit \
  -destkeystore existing-keystore.jks \
  -deststorepass existing-password \
  -destkeypass key-password \
  -noprompt
```

### Step 6: Create PKCS12 for Client Certificates (Mutual TLS)

If you need client certificates for mutual TLS authentication:

```bash
# Create client PKCS12 from client certificate and key
openssl pkcs12 -export \
  -in client.crt \
  -inkey client.key \
  -out client.p12 \
  -name rabbitmq-client \
  -password pass:changeit

# If you have a CA certificate for the client
openssl pkcs12 -export \
  -in client.crt \
  -inkey client.key \
  -certfile ca.crt \
  -out client-with-ca.p12 \
  -name rabbitmq-client \
  -password pass:changeit
```

### Step 7: Change PKCS12 Password

To change the password of an existing PKCS12 file:

```bash
# Change PKCS12 password
openssl pkcs12 -in rabbitmq-server.p12 \
  -passin pass:oldpassword \
  -passout pass:newpassword \
  -out rabbitmq-server-new.p12

# Verify with new password
openssl pkcs12 -info \
  -in rabbitmq-server-new.p12 \
  -passin pass:newpassword \
  -noout
```

### Step 8: Extract Components from PKCS12

Extract individual components for different use cases:

```bash
# Extract certificate only (PEM format)
openssl pkcs12 -in rabbitmq-server.p12 \
  -passin pass:changeit \
  -clcerts \
  -nokeys \
  -out certificate.pem

# Extract private key only (PEM format, unencrypted)
openssl pkcs12 -in rabbitmq-server.p12 \
  -passin pass:changeit \
  -nocerts \
  -nodes \
  -out private-key.pem

# Extract private key (encrypted)
openssl pkcs12 -in rabbitmq-server.p12 \
  -passin pass:changeit \
  -nocerts \
  -out private-key-encrypted.pem

# Extract CA certificates (if present)
openssl pkcs12 -in rabbitmq-server.p12 \
  -passin pass:changeit \
  -cacerts \
  -nokeys \
  -out ca-certificates.pem
```

### Step 9: Use PKCS12 Directly in Java Applications

Java can use PKCS12 files directly without conversion to JKS:

```java
import javax.net.ssl.KeyManagerFactory;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManagerFactory;
import java.io.FileInputStream;
import java.security.KeyStore;

// Load PKCS12 keystore
KeyStore keyStore = KeyStore.getInstance("PKCS12");
keyStore.load(
    new FileInputStream("/path/to/rabbitmq-server.p12"),
    "changeit".toCharArray()
);

// Create KeyManagerFactory
KeyManagerFactory kmf = KeyManagerFactory.getInstance(
    KeyManagerFactory.getDefaultAlgorithm()
);
kmf.init(keyStore, "changeit".toCharArray());

// Create SSLContext
SSLContext sslContext = SSLContext.getInstance("TLS");
sslContext.init(kmf.getKeyManagers(), null, null);

// Use with RabbitMQ ConnectionFactory
ConnectionFactory factory = new ConnectionFactory();
factory.setHost("rabbitmq.example.com");
factory.setPort(443);
factory.useSslProtocol(sslContext);
```

### Step 10: Use PKCS12 with System Properties

You can also configure Java to use PKCS12 via system properties:

```bash
# Set system properties for PKCS12
export JAVA_OPTS="-Djavax.net.ssl.keyStore=/path/to/rabbitmq-server.p12 \
  -Djavax.net.ssl.keyStoreType=PKCS12 \
  -Djavax.net.ssl.keyStorePassword=changeit \
  -Djavax.net.ssl.trustStore=/path/to/rabbitmq-truststore.jks \
  -Djavax.net.ssl.trustStorePassword=changeit"
```

### Step 11: Verify PKCS12 Certificate Details

```bash
# View detailed certificate information
openssl pkcs12 -in rabbitmq-server.p12 \
  -passin pass:changeit \
  -clcerts \
  -nokeys | openssl x509 -text -noout

# Check certificate validity dates
openssl pkcs12 -in rabbitmq-server.p12 \
  -passin pass:changeit \
  -clcerts \
  -nokeys | openssl x509 -noout -dates

# Check certificate subject and issuer
openssl pkcs12 -in rabbitmq-server.p12 \
  -passin pass:changeit \
  -clcerts \
  -nokeys | openssl x509 -noout -subject -issuer
```

### Step 12: Combine Multiple Certificates into PKCS12

If you need to bundle multiple certificates:

```bash
# First, combine certificates into a single PEM file
cat cert1.crt cert2.crt > combined-certs.pem

# Create PKCS12 with combined certificates
openssl pkcs12 -export \
  -in combined-certs.pem \
  -inkey private-key.key \
  -out combined.p12 \
  -name combined-cert \
  -password pass:changeit
```

### PKCS12 Best Practices

1. **Strong Passwords**: Always use strong, unique passwords for PKCS12 files
2. **Secure Storage**: Store PKCS12 files with restricted permissions (600)
3. **Backup**: Keep secure backups of PKCS12 files and passwords
4. **Password Management**: Use a password manager for PKCS12 passwords
5. **Certificate Validity**: Regularly check certificate expiration dates
6. **Key Protection**: Never share private keys or PKCS12 passwords

```bash
# Set secure permissions on PKCS12 file
chmod 600 rabbitmq-server.p12

# Verify permissions
ls -l rabbitmq-server.p12
```

---

## Certificate Import to Keystore for Containerized Applications

For Java applications running in containers on k3s, you need to create keystores and make them available via Kubernetes ConfigMaps or Secrets. This section covers creating keystores and deploying them to your application containers.

### Step 1: Create Java Keystore (JKS) from PEM Certificates

Create a truststore for your Java application to trust the RabbitMQ SSL certificate:

```bash
# Create a truststore and import the certificate
keytool -import -alias rabbitmq-server \
  -file tls.crt \
  -keystore rabbitmq-truststore.jks \
  -storepass changeit \
  -noprompt

# Verify the import
keytool -list -v -keystore rabbitmq-truststore.jks -storepass changeit
```

### Step 2: Create Kubernetes Secret for Java Keystore

Create a Kubernetes Secret containing the truststore for your Java application:

```bash
# Create secret with the truststore
kubectl create secret generic rabbitmq-truststore \
  --from-file=rabbitmq-truststore.jks=rabbitmq-truststore.jks \
  --namespace=your-app-namespace

# Or if you want to store the password separately
kubectl create secret generic rabbitmq-truststore \
  --from-file=rabbitmq-truststore.jks=rabbitmq-truststore.jks \
  --from-literal=truststore-password=changeit \
  --namespace=your-app-namespace
```

### Step 3: Create PKCS12 Keystore (Alternative)

If you prefer using PKCS12 format (which Java also supports):

```bash
# Create PKCS12 from certificate and key
openssl pkcs12 -export \
  -in tls.crt \
  -inkey tls.key \
  -out rabbitmq-server.p12 \
  -name rabbitmq-server \
  -password pass:changeit

# Create secret with PKCS12
kubectl create secret generic rabbitmq-truststore-p12 \
  --from-file=rabbitmq-server.p12=rabbitmq-server.p12 \
  --from-literal=truststore-password=changeit \
  --namespace=your-app-namespace
```

### Step 4: Create Secret for Client Certificates (if using mutual TLS)

If your setup requires client certificates:

```bash
# Create PKCS12 from client certificate and key
openssl pkcs12 -export \
  -in client.crt \
  -inkey client.key \
  -out client.p12 \
  -name rabbitmq-client \
  -password pass:changeit

# Create secret with client keystore
kubectl create secret generic rabbitmq-client-keystore \
  --from-file=client.p12=client.p12 \
  --from-literal=keystore-password=changeit \
  --namespace=your-app-namespace
```

---

## Application Configuration for k3s Containers

This section covers deploying Python and Java applications as containers on k3s that connect to RabbitMQ over SSL.

### Python Application Deployment on k3s

#### Step 1: Create Secret for RabbitMQ Certificate

```bash
# Create secret with RabbitMQ certificate for Python app
kubectl create secret generic rabbitmq-cert \
  --from-file=tls.crt=tls.crt \
  --namespace=your-app-namespace
```

#### Step 2: Create Secret for RabbitMQ Credentials

```bash
# Create secret with RabbitMQ credentials
kubectl create secret generic rabbitmq-credentials \
  --from-literal=username=admin \
  --from-literal=password=your-secure-password-here \
  --namespace=your-app-namespace
```

#### Step 3: Python Application Code (Container-Ready)

Create `app.py`:

```python
import os
import pika
import ssl

# Get configuration from environment variables
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST', 'rabbitmq.rabbitmq.svc.cluster.local')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', '443'))
RABBITMQ_USER = os.getenv('RABBITMQ_USER')
RABBITMQ_PASSWORD = os.getenv('RABBITMQ_PASSWORD')
RABBITMQ_CERT_PATH = os.getenv('RABBITMQ_CERT_PATH', '/etc/rabbitmq-certs/tls.crt')

# SSL Context
ssl_context = ssl.create_default_context(cafile=RABBITMQ_CERT_PATH)
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_REQUIRED  # Use CERT_REQUIRED in production

# Connection parameters
credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
parameters = pika.ConnectionParameters(
    host=RABBITMQ_HOST,
    port=RABBITMQ_PORT,
    virtual_host='/',
    credentials=credentials,
    ssl_options=pika.SSLOptions(ssl_context)
)

# Create connection
connection = pika.BlockingConnection(parameters)
channel = connection.channel()

# Use the channel for operations
channel.queue_declare(queue='test_queue')
channel.basic_publish(exchange='', routing_key='test_queue', body='Hello World!')

connection.close()
```

#### Step 4: Python Application Deployment YAML

Create `python-app-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: python-app
  namespace: your-app-namespace
spec:
  replicas: 1
  selector:
    matchLabels:
      app: python-app
  template:
    metadata:
      labels:
        app: python-app
    spec:
      containers:
      - name: python-app
        image: your-registry/python-app:latest
        env:
        - name: RABBITMQ_HOST
          value: "rabbitmq.rabbitmq.svc.cluster.local"  # Service DNS name
        - name: RABBITMQ_PORT
          value: "443"
        - name: RABBITMQ_USER
          valueFrom:
            secretKeyRef:
              name: rabbitmq-credentials
              key: username
        - name: RABBITMQ_PASSWORD
          valueFrom:
            secretKeyRef:
              name: rabbitmq-credentials
              key: password
        - name: RABBITMQ_CERT_PATH
          value: "/etc/rabbitmq-certs/tls.crt"
        volumeMounts:
        - name: rabbitmq-certs
          mountPath: /etc/rabbitmq-certs
          readOnly: true
      volumes:
      - name: rabbitmq-certs
        secret:
          secretName: rabbitmq-cert
---
apiVersion: v1
kind: Service
metadata:
  name: python-app
  namespace: your-app-namespace
spec:
  selector:
    app: python-app
  ports:
  - port: 80
    targetPort: 8080
```

### Java Application Deployment on k3s

#### Step 1: Add Dependencies (Maven)

```xml
<dependencies>
    <dependency>
        <groupId>com.rabbitmq</groupId>
        <artifactId>amqp-client</artifactId>
        <version>5.20.0</version>
    </dependency>
</dependencies>
```

#### Step 2: Java Connection Code (Container-Ready)

Create `RabbitMQConnection.java`:

```java
import com.rabbitmq.client.Connection;
import com.rabbitmq.client.ConnectionFactory;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManagerFactory;
import java.io.FileInputStream;
import java.security.KeyStore;

public class RabbitMQConnection {
    
    public static Connection createSSLConnection() throws Exception {
        ConnectionFactory factory = new ConnectionFactory();
        
        // Get configuration from environment variables
        String host = System.getenv("RABBITMQ_HOST");
        int port = Integer.parseInt(System.getenv().getOrDefault("RABBITMQ_PORT", "443"));
        String username = System.getenv("RABBITMQ_USER");
        String password = System.getenv("RABBITMQ_PASSWORD");
        String truststorePath = System.getenv("RABBITMQ_TRUSTSTORE_PATH");
        String truststorePassword = System.getenv("RABBITMQ_TRUSTSTORE_PASSWORD");
        
        // Basic connection settings
        factory.setHost(host);
        factory.setPort(port);
        factory.setUsername(username);
        factory.setPassword(password);
        factory.setVirtualHost("/");
        
        // SSL Configuration
        factory.useSslProtocol();
        
        // Load truststore from mounted volume
        KeyStore trustStore = KeyStore.getInstance("JKS");
        trustStore.load(
            new FileInputStream(truststorePath),
            truststorePassword.toCharArray()
        );
        
        TrustManagerFactory tmf = TrustManagerFactory.getInstance(
            TrustManagerFactory.getDefaultAlgorithm()
        );
        tmf.init(trustStore);
        
        SSLContext sslContext = SSLContext.getInstance("TLS");
        sslContext.init(null, tmf.getTrustManagers(), null);
        
        factory.setSslContext(sslContext);
        
        // Disable hostname verification (only for development)
        factory.setHostnameVerifier((hostname, session) -> true);
        
        return factory.newConnection();
    }
}
```

#### Step 3: Java Application Deployment YAML

Create `java-app-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: java-app
  namespace: your-app-namespace
spec:
  replicas: 1
  selector:
    matchLabels:
      app: java-app
  template:
    metadata:
      labels:
        app: java-app
    spec:
      containers:
      - name: java-app
        image: your-registry/java-app:latest
        env:
        - name: RABBITMQ_HOST
          value: "rabbitmq.rabbitmq.svc.cluster.local"  # Service DNS name
        - name: RABBITMQ_PORT
          value: "443"
        - name: RABBITMQ_USER
          valueFrom:
            secretKeyRef:
              name: rabbitmq-credentials
              key: username
        - name: RABBITMQ_PASSWORD
          valueFrom:
            secretKeyRef:
              name: rabbitmq-credentials
              key: password
        - name: RABBITMQ_TRUSTSTORE_PATH
          value: "/etc/rabbitmq-truststore/rabbitmq-truststore.jks"
        - name: RABBITMQ_TRUSTSTORE_PASSWORD
          valueFrom:
            secretKeyRef:
              name: rabbitmq-truststore
              key: truststore-password
        volumeMounts:
        - name: rabbitmq-truststore
          mountPath: /etc/rabbitmq-truststore
          readOnly: true
      volumes:
      - name: rabbitmq-truststore
        secret:
          secretName: rabbitmq-truststore
---
apiVersion: v1
kind: Service
metadata:
  name: java-app
  namespace: your-app-namespace
spec:
  selector:
    app: java-app
  ports:
  - port: 8080
    targetPort: 8080
```

#### Step 4: Using PKCS12 in Deployment (Alternative to JKS)

If you prefer using PKCS12 format, update the deployment to use the PKCS12 secret:

```yaml
# In java-app-deployment.yaml, update environment variables:
env:
- name: RABBITMQ_TRUSTSTORE_PATH
  value: "/etc/rabbitmq-truststore/rabbitmq-server.p12"
- name: RABBITMQ_TRUSTSTORE_TYPE
  value: "PKCS12"
```

And update the Java code to use PKCS12:

```java
// In RabbitMQConnection.java, change the KeyStore type:
KeyStore trustStore = KeyStore.getInstance("PKCS12");  // Instead of "JKS"
```

---

## Testing and Verification

### Step 1: Test Non-SSL Connection (Internal)

```bash
# Port forward non-SSL port
kubectl port-forward -n rabbitmq service/rabbitmq 5672:5672

# Test with rabbitmqadmin (if installed)
rabbitmqadmin -H localhost -P 5672 -u admin -p your-password list queues
```

### Step 2: Test SSL Connection via LoadBalancer

```bash
# Test SSL connection on port 443
openssl s_client -connect rabbitmq.example.com:443 -showcerts

# Test with rabbitmqadmin over SSL
rabbitmqadmin -H rabbitmq.example.com -P 443 -u admin -p your-password \
  --ssl --ssl-ca-cert-file=tls.crt list queues
```

### Step 3: Test Python Application

```bash
# Run your Python application
python your_rabbitmq_app.py

# Check for successful connection messages
```

### Step 4: Test Java Application

```bash
# Compile and run Java application
javac -cp "amqp-client-5.20.0.jar:slf4j-api-1.7.36.jar" RabbitMQSSLConnection.java
java -cp ".:amqp-client-5.20.0.jar:slf4j-api-1.7.36.jar" RabbitMQSSLConnection

# Check for successful connection
```

### Step 5: Verify RabbitMQ Management UI

```bash
# Test Management UI via LoadBalancer (HTTPS on port 8443)
curl -k https://rabbitmq-mgmt.example.com:8443/api/overview \
  -u admin:your-secure-password-here

# Test via port forward (for local testing)
kubectl port-forward -n rabbitmq service/rabbitmq 8443:8443

# Then access in browser:
# https://localhost:8443
# Username: admin
# Password: your-secure-password-here

# Verify management plugin is enabled
kubectl exec -it deployment/rabbitmq -n rabbitmq -- rabbitmq-plugins list | grep management

# Check management UI SSL certificate
openssl s_client -connect rabbitmq-mgmt.example.com:8443 -showcerts

# Test management API endpoints
curl -k -u admin:your-secure-password-here \
  https://rabbitmq-mgmt.example.com:8443/api/queues

curl -k -u admin:your-secure-password-here \
  https://rabbitmq-mgmt.example.com:8443/api/nodes
```

---

## Troubleshooting

### Issue 1: Certificate Verification Errors

**Problem**: Java/Python applications fail with certificate verification errors.

**Solution**:
- Ensure the certificate is properly imported into the truststore
- Verify the certificate chain is complete
- Check that the DNS name matches the certificate CN or SAN

```bash
# Verify certificate details
openssl x509 -in tls.crt -text -noout | grep -A 2 "Subject Alternative Name"
```

### Issue 2: Connection Refused on Port 443

**Problem**: Cannot connect to RabbitMQ on port 443.

**Solution**:
- Verify LoadBalancer service is running: `kubectl get svc -n rabbitmq`
- Check firewall rules
- Verify DNS resolution: `nslookup rabbitmq.example.com`
- Check RabbitMQ pod logs: `kubectl logs -n rabbitmq deployment/rabbitmq`

### Issue 3: SSL Handshake Failures

**Problem**: SSL handshake fails during connection.

**Solution**:
- Verify RabbitMQ SSL listener is running: Check logs for "started SSL listener"
- Ensure certificates are correctly mounted in the pod
- Verify certificate and key match: `openssl x509 -noout -modulus -in tls.crt | openssl md5` and `openssl rsa -noout -modulus -in tls.key | openssl md5` (should match)

### Issue 4: Java Keystore Issues

**Problem**: Java cannot find or read the keystore.

**Solution**:
- Verify keystore path is correct
- Check file permissions: `chmod 644 rabbitmq-truststore.jks`
- Verify keystore password is correct
- Test keystore: `keytool -list -v -keystore rabbitmq-truststore.jks`

### Issue 5: Cannot Enable Management Plugin - Read-only Filesystem

**Problem**: Error when trying to enable management plugin: `{:cannot_write_enabled_plugins_file, ~c"/etc/rabbitmq/enabled_plugins", :erofs}`

**Solution**: The `/etc/rabbitmq` directory is read-only in the container. Use a ConfigMap to provide the `enabled_plugins` file:

```bash
# Create enabled_plugins file
cat > enabled_plugins <<EOF
[rabbitmq_management,rabbitmq_management_agent].
EOF

# Create ConfigMap
kubectl create configmap rabbitmq-enabled-plugins \
  --from-file=enabled_plugins \
  --namespace=rabbitmq

# Update deployment to mount this ConfigMap (add to volumeMounts and volumes)
# Then restart the deployment
kubectl rollout restart deployment/rabbitmq -n rabbitmq

# Verify after restart
kubectl exec -it deployment/rabbitmq -n rabbitmq -- rabbitmq-plugins list | grep management
```

See [Management Plugin Configuration - Step 1](#step-1-enable-management-plugin) for detailed instructions.

### Issue 6: RabbitMQ Pod Not Starting

**Problem**: RabbitMQ container fails to start.

**Solution**:
- Check pod status: `kubectl describe pod -n rabbitmq -l app=rabbitmq`
- Check logs: `kubectl logs -n rabbitmq deployment/rabbitmq`
- Verify ConfigMap is correct: `kubectl get configmap rabbitmq-config -n rabbitmq -o yaml`
- Verify secrets exist: `kubectl get secret -n rabbitmq`

### Issue 6: DNS Resolution Issues

**Problem**: Applications cannot resolve RabbitMQ DNS name.

**Solution**:
- Verify DNS records: `dig rabbitmq.example.com` or `nslookup rabbitmq.example.com`
- Check /etc/hosts if using local testing
- Verify LoadBalancer external IP matches DNS A record

---

## Security Best Practices

1. **Change Default Passwords**: Always change default RabbitMQ credentials
2. **Use Strong Passwords**: Use complex passwords for RabbitMQ users
3. **Restrict Access**: Use NetworkPolicies to restrict access to RabbitMQ pods
4. **Certificate Rotation**: Implement certificate rotation procedures
5. **Enable Certificate Verification**: In production, enable proper certificate verification
6. **Use Secrets Management**: Store passwords in Kubernetes secrets, not in code
7. **Monitor Connections**: Regularly monitor RabbitMQ connections and queues
8. **Update Regularly**: Keep RabbitMQ and k3s updated with security patches

---

## Additional Resources

- [RabbitMQ SSL/TLS Documentation](https://www.rabbitmq.com/ssl.html)
- [RabbitMQ Kubernetes Guide](https://www.rabbitmq.com/kubernetes/operator/operator-overview.html)
- [k3s Documentation](https://docs.k3s.io/)
- [Java Keytool Guide](https://docs.oracle.com/javase/8/docs/technotes/tools/unix/keytool.html)

---

## Quick Reference Commands

```bash
# Check RabbitMQ deployment
kubectl get deployment -n rabbitmq

# Check services
kubectl get svc -n rabbitmq

# View RabbitMQ logs
kubectl logs -f deployment/rabbitmq -n rabbitmq

# Port forward for testing
kubectl port-forward -n rabbitmq service/rabbitmq 5672:5672
kubectl port-forward -n rabbitmq service/rabbitmq-ssl-lb 443:443
kubectl port-forward -n rabbitmq service/rabbitmq-management-lb 8443:8443

# Test SSL connection
openssl s_client -connect rabbitmq.example.com:443

# Test Management UI
curl -k https://rabbitmq-mgmt.example.com:8443/api/overview -u admin:password
openssl s_client -connect rabbitmq-mgmt.example.com:8443 -showcerts

# Create enabled_plugins ConfigMap (for read-only filesystem)
echo '[rabbitmq_management,rabbitmq_management_agent].' > enabled_plugins
kubectl create configmap rabbitmq-enabled-plugins \
  --from-file=enabled_plugins --namespace=rabbitmq

# Verify management plugin is enabled
kubectl exec -it deployment/rabbitmq -n rabbitmq -- rabbitmq-plugins list | grep management

# Create PKCS12 from certificate and key
openssl pkcs12 -export -in tls.crt -inkey tls.key \
  -out rabbitmq-server.p12 -name rabbitmq-server -password pass:changeit

# Verify PKCS12 file
openssl pkcs12 -info -in rabbitmq-server.p12 -passin pass:changeit -noout

# Convert PKCS12 to JKS
keytool -importkeystore -srckeystore rabbitmq-server.p12 \
  -srcstoretype PKCS12 -srcstorepass changeit \
  -destkeystore rabbitmq-server.jks -deststoretype JKS \
  -deststorepass changeit -noprompt

# Import certificate to keystore (from PEM)
keytool -import -alias rabbitmq-server -file tls.crt \
  -keystore rabbitmq-truststore.jks -storepass changeit -noprompt

# Create Kubernetes secret for Java truststore
kubectl create secret generic rabbitmq-truststore \
  --from-file=rabbitmq-truststore.jks=rabbitmq-truststore.jks \
  --from-literal=truststore-password=changeit \
  --namespace=your-app-namespace

# Create Kubernetes secret for Python certificate
kubectl create secret generic rabbitmq-cert \
  --from-file=tls.crt=tls.crt \
  --namespace=your-app-namespace

# List keystore contents
keytool -list -v -keystore rabbitmq-truststore.jks -storepass changeit

# Extract certificate from PKCS12
openssl pkcs12 -in rabbitmq-server.p12 -passin pass:changeit \
  -clcerts -nokeys -out extracted-cert.pem

# Extract private key from PKCS12
openssl pkcs12 -in rabbitmq-server.p12 -passin pass:changeit \
  -nocerts -nodes -out extracted-key.pem

# Create client certificate from server certificate (simple copy for dev/test)
cp tls.crt client.crt && cp tls.key client.key

# Generate new client private key
openssl genrsa -out client.key 2048

# Create self-signed client certificate
openssl req -new -x509 -key client.key -out client.crt -days 365 \
  -subj "/CN=rabbitmq-client/O=Client"

# Create client PKCS12 from client certificate and key
openssl pkcs12 -export -in client.crt -inkey client.key \
  -out client.p12 -name rabbitmq-client -password pass:changeit

# Verify client certificate and key match
openssl x509 -noout -modulus -in client.crt | openssl md5
openssl rsa -noout -modulus -in client.key | openssl md5
```

---

**Document Version**: 1.0  
**Last Updated**: 2025-01-27
