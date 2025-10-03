# Phase 2: GCP Infrastructure Setup

**Date Started**: October 3, 2025
**Status**: 🔄 In Progress
**Branch**: feature/gcp-kubernetes-deployment
**Previous Phase**: Phase 1 - Docker Containerization ✅ COMPLETE

## Overview

Set up Google Cloud Platform (GCP) infrastructure to host the containerized MizzouNewsCrawler application in a production-ready environment.

## Prerequisites

- [x] Phase 1 Complete - Docker containers built and tested locally
- [ ] GCP Account with billing enabled
- [ ] gcloud CLI installed and authenticated
- [ ] kubectl installed
- [ ] Appropriate GCP permissions (Project Owner or Editor + specific service permissions)

## Objectives

1. Create and configure GCP project
2. Set up container registry (Artifact Registry or GCR)
3. Push Docker images to GCP
4. Create Cloud SQL PostgreSQL instance
5. Set up Google Kubernetes Engine (GKE) cluster
6. Deploy services to Kubernetes
7. Configure networking and load balancing
8. Set up monitoring and logging
9. Implement secrets management
10. Test end-to-end deployment

## Architecture Design

### Services
- **API Service**: FastAPI backend (Deployment + Service + Ingress)
- **Crawler Service**: Background job runner (CronJob)
- **Processor Service**: Background job runner (CronJob)
- **Database**: Cloud SQL PostgreSQL (managed service)

### GCP Services Required
- **Google Kubernetes Engine (GKE)**: Container orchestration
- **Cloud SQL**: Managed PostgreSQL database
- **Artifact Registry**: Docker image storage
- **Cloud Storage**: File storage for artifacts/logs
- **Cloud Logging**: Centralized logging
- **Cloud Monitoring**: Metrics and alerting
- **Secret Manager**: Secure credential storage
- **VPC**: Network isolation
- **Cloud Load Balancing**: External access to API

## Step-by-Step Implementation

### Step 1: GCP Project Setup

#### 1.1 Install and Configure gcloud CLI
```bash
# Install gcloud (if not already installed)
# macOS: brew install google-cloud-sdk
# Or download from: https://cloud.google.com/sdk/docs/install

# Initialize and authenticate
gcloud init

# Verify installation
gcloud --version
```

#### 1.2 Create GCP Project
```bash
# Set variables
export PROJECT_ID="mizzou-news-crawler"
export PROJECT_NAME="MizzouNewsCrawler"
export BILLING_ACCOUNT_ID="YOUR_BILLING_ACCOUNT_ID"

# Create project
gcloud projects create $PROJECT_ID --name="$PROJECT_NAME"

# Set as default project
gcloud config set project $PROJECT_ID

# Link billing account
gcloud billing projects link $PROJECT_ID --billing-account=$BILLING_ACCOUNT_ID
```

#### 1.3 Enable Required APIs
```bash
# Enable all required GCP APIs
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
  servicenetworking.googleapis.com
```

### Step 2: Artifact Registry Setup

#### 2.1 Create Docker Repository
```bash
# Set region
export REGION="us-central1"
export REPO_NAME="mizzou-crawler"

# Create Artifact Registry repository
gcloud artifacts repositories create $REPO_NAME \
  --repository-format=docker \
  --location=$REGION \
  --description="MizzouNewsCrawler Docker images"

# Configure Docker authentication
gcloud auth configure-docker ${REGION}-docker.pkg.dev
```

#### 2.2 Tag and Push Images
```bash
# Set image variables
export IMAGE_TAG="v1.0.0"
export REGISTRY_URL="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}"

# Tag images
docker tag mizzounewscrawler-scripts-api:latest \
  ${REGISTRY_URL}/api:${IMAGE_TAG}

docker tag mizzounewscrawler-scripts-crawler:latest \
  ${REGISTRY_URL}/crawler:${IMAGE_TAG}

docker tag mizzounewscrawler-scripts-processor:latest \
  ${REGISTRY_URL}/processor:${IMAGE_TAG}

# Push to Artifact Registry
docker push ${REGISTRY_URL}/api:${IMAGE_TAG}
docker push ${REGISTRY_URL}/crawler:${IMAGE_TAG}
docker push ${REGISTRY_URL}/processor:${IMAGE_TAG}

# Also tag as 'latest'
docker tag ${REGISTRY_URL}/api:${IMAGE_TAG} ${REGISTRY_URL}/api:latest
docker tag ${REGISTRY_URL}/crawler:${IMAGE_TAG} ${REGISTRY_URL}/crawler:latest
docker tag ${REGISTRY_URL}/processor:${IMAGE_TAG} ${REGISTRY_URL}/processor:latest

docker push ${REGISTRY_URL}/api:latest
docker push ${REGISTRY_URL}/crawler:latest
docker push ${REGISTRY_URL}/processor:latest
```

### Step 3: Cloud SQL Setup

#### 3.1 Create PostgreSQL Instance
```bash
# Set database variables
export DB_INSTANCE_NAME="mizzou-db-prod"
export DB_VERSION="POSTGRES_16"
export DB_TIER="db-g1-small"  # Start small, can scale up
export DB_REGION=$REGION

# Create Cloud SQL instance
gcloud sql instances create $DB_INSTANCE_NAME \
  --database-version=$DB_VERSION \
  --tier=$DB_TIER \
  --region=$DB_REGION \
  --network=default \
  --enable-bin-log \
  --backup-start-time=03:00 \
  --maintenance-window-day=SUN \
  --maintenance-window-hour=04

# Wait for instance to be ready (takes 5-10 minutes)
gcloud sql instances list
```

#### 3.2 Create Database and User
```bash
# Set database credentials
export DB_NAME="mizzou"
export DB_USER="mizzou_user"
export DB_PASSWORD=$(openssl rand -base64 32)  # Generate secure password

# Create database
gcloud sql databases create $DB_NAME --instance=$DB_INSTANCE_NAME

# Create user
gcloud sql users create $DB_USER \
  --instance=$DB_INSTANCE_NAME \
  --password=$DB_PASSWORD

# Save password to Secret Manager
echo -n $DB_PASSWORD | gcloud secrets create db-password --data-file=-

# Get connection name for later use
export DB_CONNECTION_NAME=$(gcloud sql instances describe $DB_INSTANCE_NAME --format='value(connectionName)')
echo "Connection Name: $DB_CONNECTION_NAME"
```

### Step 4: GKE Cluster Setup

#### 4.1 Create GKE Cluster
```bash
# Set cluster variables
export CLUSTER_NAME="mizzou-cluster"
export CLUSTER_ZONE="${REGION}-a"
export NODE_MACHINE_TYPE="e2-standard-2"  # 2 vCPU, 8GB RAM
export NUM_NODES=2

# Create GKE cluster with Workload Identity
gcloud container clusters create $CLUSTER_NAME \
  --zone=$CLUSTER_ZONE \
  --num-nodes=$NUM_NODES \
  --machine-type=$NODE_MACHINE_TYPE \
  --enable-autoscaling \
  --min-nodes=1 \
  --max-nodes=5 \
  --enable-autorepair \
  --enable-autoupgrade \
  --workload-pool=${PROJECT_ID}.svc.id.goog \
  --addons=HorizontalPodAutoscaling,HttpLoadBalancing,GcePersistentDiskCsiDriver

# Get cluster credentials
gcloud container clusters get-credentials $CLUSTER_NAME --zone=$CLUSTER_ZONE

# Verify connection
kubectl cluster-info
kubectl get nodes
```

#### 4.2 Create Kubernetes Namespaces
```bash
# Create namespace for production
kubectl create namespace production

# Set default namespace
kubectl config set-context --current --namespace=production
```

### Step 5: Kubernetes Configuration

#### 5.1 Create ConfigMaps
Create file: `k8s/configmap.yaml`
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
  namespace: production
data:
  LOG_LEVEL: "INFO"
  PYTHONUNBUFFERED: "1"
  PYTHONDONTWRITEBYTECODE: "1"
  GCS_BUCKET: "mizzou-raw-assets"
  BIGQUERY_DATASET: "mizzou_analytics"
```

#### 5.2 Create Secrets
```bash
# Create database connection secret
kubectl create secret generic db-secret \
  --namespace=production \
  --from-literal=username=$DB_USER \
  --from-literal=password=$DB_PASSWORD \
  --from-literal=database=$DB_NAME \
  --from-literal=connection-name=$DB_CONNECTION_NAME

# Verify secret created
kubectl get secrets -n production
```

#### 5.3 Create Deployments, Services, and CronJobs
Create files in `k8s/` directory (to be created in next steps).

### Step 6: Deploy to GKE

#### 6.1 Deploy API Service
```bash
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/api-service.yaml
kubectl apply -f k8s/api-ingress.yaml
```

#### 6.2 Deploy Crawler CronJob
```bash
kubectl apply -f k8s/crawler-cronjob.yaml
```

#### 6.3 Deploy Processor CronJob
```bash
kubectl apply -f k8s/processor-cronjob.yaml
```

#### 6.4 Verify Deployments
```bash
# Check all resources
kubectl get all -n production

# Check pods
kubectl get pods -n production

# Check logs
kubectl logs -f deployment/api -n production

# Check services
kubectl get services -n production

# Check ingress (if configured)
kubectl get ingress -n production
```

### Step 7: Networking and Load Balancing

#### 7.1 Configure Ingress
```bash
# Install NGINX Ingress Controller (if not using GKE ingress)
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.1/deploy/static/provider/cloud/deploy.yaml

# Wait for external IP
kubectl get service -n ingress-nginx
```

#### 7.2 Set Up SSL/TLS (Optional but Recommended)
```bash
# Using cert-manager for Let's Encrypt certificates
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml

# Create ClusterIssuer for Let's Encrypt
kubectl apply -f k8s/cert-issuer.yaml
```

### Step 8: Monitoring and Logging

#### 8.1 Enable GCP Logging
```bash
# Cloud Logging is enabled by default on GKE
# View logs in GCP Console: Logging > Logs Explorer

# Query logs from CLI
gcloud logging read "resource.type=k8s_container AND resource.labels.namespace_name=production" --limit 50
```

#### 8.2 Set Up Monitoring
```bash
# Cloud Monitoring is enabled by default
# Create alerts and dashboards in GCP Console: Monitoring

# Example: Create uptime check for API
gcloud monitoring uptime-checks create \
  --display-name="API Health Check" \
  --resource-type=uptime-url \
  --host=YOUR_API_DOMAIN \
  --path=/api/ui_overview
```

## Current Progress

- [ ] Step 1: GCP Project Setup
  - [ ] Install gcloud CLI
  - [ ] Create GCP project
  - [ ] Enable required APIs
  
- [ ] Step 2: Artifact Registry
  - [ ] Create Docker repository
  - [ ] Tag and push images
  
- [ ] Step 3: Cloud SQL
  - [ ] Create PostgreSQL instance
  - [ ] Create database and user
  - [ ] Configure connection
  
- [ ] Step 4: GKE Cluster
  - [ ] Create cluster
  - [ ] Configure kubectl
  - [ ] Create namespaces
  
- [ ] Step 5: Kubernetes Configuration
  - [ ] Create ConfigMaps
  - [ ] Create Secrets
  - [ ] Create deployment manifests
  
- [ ] Step 6: Deploy to GKE
  - [ ] Deploy API
  - [ ] Deploy Crawler
  - [ ] Deploy Processor
  - [ ] Verify all services
  
- [ ] Step 7: Networking
  - [ ] Configure ingress
  - [ ] Set up load balancer
  - [ ] Configure SSL (optional)
  
- [ ] Step 8: Monitoring
  - [ ] Set up logging
  - [ ] Create dashboards
  - [ ] Configure alerts

## Files to Create

1. `k8s/configmap.yaml` - Application configuration
2. `k8s/api-deployment.yaml` - API deployment manifest
3. `k8s/api-service.yaml` - API service (LoadBalancer or ClusterIP)
4. `k8s/api-ingress.yaml` - Ingress configuration (optional)
5. `k8s/crawler-cronjob.yaml` - Crawler scheduled job
6. `k8s/processor-cronjob.yaml` - Processor scheduled job
7. `k8s/cloud-sql-proxy.yaml` - Cloud SQL Proxy sidecar (if needed)
8. `k8s/cert-issuer.yaml` - Certificate issuer for SSL (optional)

## Cost Estimation (Monthly)

- **GKE Cluster**: ~$150-200/month (2 e2-standard-2 nodes)
- **Cloud SQL**: ~$50-100/month (db-g1-small instance)
- **Load Balancer**: ~$20/month
- **Artifact Registry**: ~$5-10/month
- **Cloud Storage**: ~$5-20/month (depends on usage)
- **Networking**: ~$10-30/month (egress traffic)

**Total Estimated**: ~$240-380/month

Can scale down for development/testing or up for production load.

## Security Considerations

1. **Workload Identity**: Use GCP Workload Identity instead of service account keys
2. **Secret Manager**: Store all sensitive data in Secret Manager
3. **Network Policies**: Restrict pod-to-pod communication
4. **Private GKE**: Use private cluster for production (nodes not publicly accessible)
5. **Cloud Armor**: Add DDoS protection and WAF rules
6. **VPC Service Controls**: Restrict data exfiltration
7. **Binary Authorization**: Require signed container images

## Next Steps

After completing Phase 2:
- **Phase 3**: Database migration and initialization
- **Phase 4**: CI/CD pipeline setup (GitHub Actions)
- **Phase 5**: Production testing and optimization
- **Phase 6**: Monitoring, alerting, and operational runbooks
- **Phase 7**: Documentation and handoff

---

**Phase 2 Status**: 🔄 **IN PROGRESS**
**Estimated Completion**: TBD
**Blockers**: None currently
