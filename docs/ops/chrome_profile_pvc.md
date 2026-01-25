# Chrome Profile PVC (Persistent mount for Selenium profile)

This document describes how to persist a Chrome `User Data` profile inside the cluster so extraction jobs can mount it.

Why use a PVC?
- Kubernetes Secrets have a 1 MiB size limit for the `data` field. Large Chrome profiles (>~1 MiB) cannot be stored as a single secret.
- A PersistentVolumeClaim (PVC) allows us to store the packed profile (or the extracted directory) persistently and mount it as a read-only profile into extraction jobs.

Steps performed (automated by the team):

1) Create a PVC (example):

```bash
cat <<'YAML' | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: chrome-profile-macos-default-pvc
  namespace: production
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi
  storageClassName: standard-rwo
YAML
```

2) Provision a short-lived populator pod that mounts the PVC (so the PVC is provisioned and available):

```bash
cat <<'YAML' | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: chrome-profile-populator
  namespace: production
spec:
  containers:
    - name: populator
      image: alpine:3.18
      command: ["/bin/sh", "-c", "sleep 3600"]
      volumeMounts:
        - name: chrome-profile-data
          mountPath: /mnt/profile
  restartPolicy: Never
  volumes:
    - name: chrome-profile-data
      persistentVolumeClaim:
        claimName: chrome-profile-macos-default-pvc
YAML
```

3) Copy the local tarball into the populator and extract it:

```bash
kubectl cp /path/to/chrome_profile_default_20260107T192110Z.tar.gz \
  production/chrome-profile-populator:/mnt/profile/chrome_profile.tar.gz -c populator

kubectl exec -n production pod/chrome-profile-populator -c populator -- \
  sh -c 'tar -xzf /mnt/profile/chrome_profile.tar.gz -C /mnt/profile && rm /mnt/profile/chrome_profile.tar.gz && chown -R 1000:1000 /mnt/profile'
```

4) Delete helper pod when finished:

```bash
kubectl delete pod chrome-profile-populator -n production
```

5) Job/Deployment changes (already applied by the team):
- Extraction jobs mount the PVC `chrome-profile-macos-default-pvc` at `/var/selenium/profile` (readOnly: true).
- The extractor reads `SELENIUM_USER_DATA_DIR=/var/selenium/profile` and `SELENIUM_PROFILE_READONLY=true` (current default) and copies the profile to a writable scratch directory for Chrome to use.

Notes & security:
- The profile contains sensitive data (cookies, localStorage). Ensure RBAC on the `production` namespace is restricted.
- If you prefer alternate persistence (GCS/PVC with GCSFuse, or an init container that downloads from a protected bucket), we can implement that instead.

If you'd like, I can also automate the PVC + upload process via a small script under `scripts/` so you can reproduce it easily.
