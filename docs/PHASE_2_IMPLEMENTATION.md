# Phase 2: Implementation Plan - LocalNewsImpact

**Organization**: localnewsimpact.org  
**Project**: MizzouNewsCrawler  
**Domain**: compute.localnewsimpact.org  
**Region**: us-central1  
**Date**: October 3, 2025

## Configuration Summary

### GCP Details
- **Organization**: localnewsimpact.org
- **Project ID**: `mizzou-news-crawler` (to be created)
- **Region**: us-central1 (Iowa - good balance of cost/performance)
- **Domain**: compute.localnewsimpact.org
- **SSL**: Required (we'll use Let's Encrypt via cert-manager)

### Requirements
- ✅ GCP account exists (localnewsimpact.org)
- ✅ Billing enabled
- ⚠️ New project needed
- ⚠️ gcloud CLI needs installation
- ⚠️ kubectl needs installation
- ⚠️ SSL certificate setup required
- ⚠️ Data migration from local SQLite

### Budget Constraints
- Start with development tier (~$100-150/month)
- Can scale to production tier later
- Focus on cost optimization initially

---

## Phase 2.1: Prerequisites Installation (START HERE)

### Step 1: Install gcloud CLI

```bash
# Install Google Cloud SDK on macOS
brew install google-cloud-sdk

# Or if brew is not available, download from:
# https://cloud.google.com/sdk/docs/install

# Verify installation
gcloud --version

# Expected output:
# Google Cloud SDK 450.0.0+
# bq 2.0.98
# core 2023.10.03
# gcloud 2023.10.03
# gsutil 5.27
```

### Step 2: Install kubectl

```bash
# Install kubectl on macOS
brew install kubectl

# Or install via gcloud components
gcloud components install kubectl

# Verify installation
kubectl version --client

# Expected output:
# Client Version: v1.28.x
```

### Step 3: Authenticate to GCP

```bash
# Login to GCP
gcloud auth login

# This will open browser for authentication
# Login with your localnewsimpact.org account

# Set the organization
gcloud organizations list
# Note the ORGANIZATION_ID

# Verify authentication
gcloud auth list
```

---

## Phase 2.2: GCP Project Setup

### Step 1: Create GCP Project

```bash
# Set variables
export ORG_ID="YOUR_ORG_ID_FROM_PREVIOUS_STEP"
export PROJECT_ID="mizzou-news-crawler"
export PROJECT_NAME="MizzouNewsCrawler"
export REGION="us-central1"

# Create project under organization
gcloud projects create $PROJECT_ID \
  --name="$PROJECT_NAME" \
  --organization=$ORG_ID

# Set as default project
gcloud config set project $PROJECT_ID

# Link billing account (you'll need the billing account ID)
gcloud billing accounts list
export BILLING_ACCOUNT_ID="YOUR_BILLING_ACCOUNT_ID"
gcloud billing projects link $PROJECT_ID --billing-account=$BILLING_ACCOUNT_ID

# Verify project created
gcloud projects describe $PROJECT_ID
```

### Step 2: Enable Required APIs

```bash
# Enable all required APIs (takes 2-3 minutes)
gcloud services enable \
  container.googleapis.com \
  sqladmin.googleapis.com \
  artifactregistry.googleapis.com \
  cloudresourcemanager.googleapis.com \
  compute.googleapis.com \
  storage.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  secretmanager.googleapis.com \
  servicenetworking.googleapis.com \
  dns.googleapis.com

# Verify APIs enabled
gcloud services list --enabled
```

### Step 3: Set Up Service Account

```bash
# Create service account for GKE
gcloud iam service-accounts create gke-mizzou-sa \
  --display-name="GKE Mizzou Service Account"

# Grant necessary roles
export SA_EMAIL="gke-mizzou-sa@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/logging.logWriter"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/monitoring.metricWriter"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/cloudsql.client"
```

---

## Phase 2.3: Artifact Registry & Image Push

### Step 1: Create Artifact Registry

```bash
export REPO_NAME="mizzou-crawler"

# Create Docker repository
gcloud artifacts repositories create $REPO_NAME \
  --repository-format=docker \
  --location=$REGION \
  --description="MizzouNewsCrawler Docker images"

# Configure Docker authentication
gcloud auth configure-docker ${REGION}-docker.pkg.dev

# Verify repository created
gcloud artifacts repositories list
```

### Step 2: Tag and Push Images

```bash
export IMAGE_TAG="v1.0.0"
export REGISTRY_URL="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}"

# Build images if not already built
cd /Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler-Scripts
docker compose build --no-cache

# Tag images
docker tag mizzounewscrawler-scripts-api:latest ${REGISTRY_URL}/api:${IMAGE_TAG}
docker tag mizzounewscrawler-scripts-crawler:latest ${REGISTRY_URL}/crawler:${IMAGE_TAG}
docker tag mizzounewscrawler-scripts-processor:latest ${REGISTRY_URL}/processor:${IMAGE_TAG}

# Also tag as 'latest'
docker tag ${REGISTRY_URL}/api:${IMAGE_TAG} ${REGISTRY_URL}/api:latest
docker tag ${REGISTRY_URL}/crawler:${IMAGE_TAG} ${REGISTRY_URL}/crawler:latest
docker tag ${REGISTRY_URL}/processor:${IMAGE_TAG} ${REGISTRY_URL}/processor:latest

# Push to Artifact Registry
echo "Pushing API image..."
docker push ${REGISTRY_URL}/api:${IMAGE_TAG}
docker push ${REGISTRY_URL}/api:latest

echo "Pushing Crawler image..."
docker push ${REGISTRY_URL}/crawler:${IMAGE_TAG}
docker push ${REGISTRY_URL}/crawler:latest

echo "Pushing Processor image..."
docker push ${REGISTRY_URL}/processor:${IMAGE_TAG}
docker push ${REGISTRY_URL}/processor:latest

# Verify images pushed
gcloud artifacts docker images list ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}
```

---

## Phase 2.4: Cloud SQL Setup

### Step 1: Create PostgreSQL Instance

```bash
export DB_INSTANCE_NAME="mizzou-db-prod"
export DB_VERSION="POSTGRES_16"
export DB_TIER="db-f1-micro"  # Smallest tier for development ($7-10/month)
export DB_REGION=$REGION

# Create Cloud SQL instance (takes 5-10 minutes)
gcloud sql instances create $DB_INSTANCE_NAME \
  --database-version=$DB_VERSION \
  --tier=$DB_TIER \
  --region=$DB_REGION \
  --network=default \
  --no-assign-ip \
  --enable-bin-log \
  --backup-start-time=03:00 \
  --maintenance-window-day=SUN \
  --maintenance-window-hour=04 \
  --root-password=$(openssl rand -base64 32)

# Wait for creation
echo "Waiting for Cloud SQL instance to be ready..."
gcloud sql operations list --instance=$DB_INSTANCE_NAME
```

### Step 2: Create Database and User

```bash
# Set database credentials
export DB_NAME="mizzou"
export DB_USER="mizzou_user"
export DB_PASSWORD=$(openssl rand -base64 32)

# Save password for later
echo "Database Password: $DB_PASSWORD" > ~/.mizzou-db-password.txt
chmod 600 ~/.mizzou-db-password.txt

# Create database
gcloud sql databases create $DB_NAME --instance=$DB_INSTANCE_NAME

# Create user
gcloud sql users create $DB_USER \
  --instance=$DB_INSTANCE_NAME \
  --password=$DB_PASSWORD

# Get connection name
export DB_CONNECTION_NAME=$(gcloud sql instances describe $DB_INSTANCE_NAME --format='value(connectionName)')
echo "DB Connection Name: $DB_CONNECTION_NAME"
echo "Save this for Kubernetes configuration: $DB_CONNECTION_NAME"

# Store in Secret Manager
echo -n $DB_PASSWORD | gcloud secrets create db-password --data-file=-
echo -n $DB_USER | gcloud secrets create db-user --data-file=-
echo -n $DB_NAME | gcloud secrets create db-name --data-file=-
echo -n $DB_CONNECTION_NAME | gcloud secrets create db-connection-name --data-file=-
```

### Step 3: Data Migration (If Needed)

```bash
# Export data from local SQLite
cd /Users/kiesowd/VSCode/NewsCrawler/MizzouNewsCrawler-Scripts

# Create SQL dump of relevant tables (customize as needed)
sqlite3 data/mizzou.db .dump > /tmp/mizzou-export.sql

# Install Cloud SQL Proxy for local connection
curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.8.0/cloud-sql-proxy.darwin.arm64
chmod +x cloud-sql-proxy
sudo mv cloud-sql-proxy /usr/local/bin/

# Connect via proxy
cloud-sql-proxy $DB_CONNECTION_NAME &
PROXY_PID=$!

# Import data (customize based on your schema)
# This is a template - you'll need to adjust for your specific tables
PGPASSWORD=$DB_PASSWORD psql -h 127.0.0.1 -U $DB_USER -d $DB_NAME < /tmp/mizzou-export.sql

# Kill proxy
kill $PROXY_PID
```

---

## Phase 2.5: GKE Cluster Setup

### Step 1: Create GKE Cluster

```bash
export CLUSTER_NAME="mizzou-cluster"
export CLUSTER_ZONE="${REGION}-a"
export NODE_MACHINE_TYPE="e2-small"  # Small for dev ($13-15/month per node)
export NUM_NODES=1  # Start with 1 node for development

# Create cluster (takes 5-10 minutes)
gcloud container clusters create $CLUSTER_NAME \
  --zone=$CLUSTER_ZONE \
  --num-nodes=$NUM_NODES \
  --machine-type=$NODE_MACHINE_TYPE \
  --enable-autoscaling \
  --min-nodes=1 \
  --max-nodes=3 \
  --enable-autorepair \
  --enable-autoupgrade \
  --workload-pool=${PROJECT_ID}.svc.id.goog \
  --service-account=${SA_EMAIL} \
  --addons=HorizontalPodAutoscaling,HttpLoadBalancing

# Get credentials
gcloud container clusters get-credentials $CLUSTER_NAME --zone=$CLUSTER_ZONE

# Verify connection
kubectl cluster-info
kubectl get nodes
```

### Step 2: Create Namespace

```bash
# Create production namespace
kubectl create namespace production

# Set as default
kubectl config set-context --current --namespace=production

# Verify
kubectl get namespaces
```

---

## Phase 2.6: Domain & SSL Setup

### Step 1: Configure Cloud DNS (If DNS managed by GCP)

```bash
# Create DNS zone (skip if DNS is managed elsewhere)
gcloud dns managed-zones create mizzou-zone \
  --dns-name="localnewsimpact.org." \
  --description="LocalNewsImpact DNS zone"

# Get nameservers
gcloud dns managed-zones describe mizzou-zone --format="value(nameServers)"
# You'll need to update these at your domain registrar
```

### Step 2: Reserve Static IP

```bash
# Reserve static IP for load balancer
gcloud compute addresses create mizzou-api-ip \
  --global

# Get the IP address
export STATIC_IP=$(gcloud compute addresses describe mizzou-api-ip --global --format="value(address)")
echo "Static IP: $STATIC_IP"
echo "Create A record: compute.localnewsimpact.org -> $STATIC_IP"
```

### Step 3: Install cert-manager for SSL

```bash
# Install cert-manager
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml

# Wait for cert-manager to be ready
kubectl wait --for=condition=Available --timeout=300s deployment/cert-manager -n cert-manager
kubectl wait --for=condition=Available --timeout=300s deployment/cert-manager-webhook -n cert-manager
kubectl wait --for=condition=Available --timeout=300s deployment/cert-manager-cainjector -n cert-manager
```

---

## Phase 2.7: Kubernetes Deployments

I'll create all the necessary Kubernetes manifests in the next step. This includes:

1. ConfigMap for application configuration
2. Secrets for database credentials
3. API Deployment with Cloud SQL Proxy sidecar
4. API Service (LoadBalancer)
5. API Ingress with SSL
6. Crawler CronJob
7. Processor CronJob

---

## Progress Checklist

### Prerequisites
- [ ] Install gcloud CLI
- [ ] Install kubectl
- [ ] Authenticate to GCP

### Project Setup
- [ ] Create GCP project
- [ ] Enable APIs
- [ ] Set up service account

### Artifact Registry
- [ ] Create repository
- [ ] Tag Docker images
- [ ] Push images to GCP

### Cloud SQL
- [ ] Create PostgreSQL instance
- [ ] Create database and user
- [ ] Migrate data (if needed)

### GKE Cluster
- [ ] Create cluster
- [ ] Get credentials
- [ ] Create namespace

### Domain & SSL
- [ ] Configure DNS
- [ ] Reserve static IP
- [ ] Install cert-manager

### Kubernetes Deployment
- [ ] Create ConfigMaps
- [ ] Create Secrets
- [ ] Deploy API
- [ ] Deploy Crawler
- [ ] Deploy Processor
- [ ] Configure Ingress with SSL

### Testing
- [ ] Verify API accessible at compute.localnewsimpact.org
- [ ] Test SSL certificate
- [ ] Test database connection
- [ ] Run crawler job manually
- [ ] Run processor job manually

---

## Estimated Timeline

- **Prerequisites Installation**: 15 minutes
- **Project Setup**: 15 minutes
- **Artifact Registry & Push**: 20 minutes
- **Cloud SQL Setup**: 15 minutes (+ 5-10 min wait time)
- **Data Migration**: 30 minutes (depends on data volume)
- **GKE Cluster**: 10 minutes (+ 5-10 min wait time)
- **Domain & SSL**: 20 minutes (+ DNS propagation time)
- **Kubernetes Deployment**: 30 minutes
- **Testing & Verification**: 30 minutes

**Total Active Time**: ~3 hours  
**Total With Wait Times**: 4-5 hours

---

## Cost Estimate (Monthly)

### Development Configuration
- GKE Cluster (1 e2-small node): ~$15
- Cloud SQL (db-f1-micro): ~$10
- Load Balancer: ~$20
- Artifact Registry: ~$5
- Cloud Storage: ~$2
- Networking: ~$10

**Total Development**: ~$62/month

### Can Scale To Production
- GKE Cluster (2 e2-standard-2 nodes): ~$150
- Cloud SQL (db-g1-small): ~$50
- Other services: ~$40

**Total Production**: ~$240/month

---

## Next Action

Run this command to start:

```bash
# Install gcloud CLI
brew install google-cloud-sdk

# Then proceed with authentication
gcloud init
```

Ready to begin? Let me know when you've installed gcloud and I'll help with the next steps!
