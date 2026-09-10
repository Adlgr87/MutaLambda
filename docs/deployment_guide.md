# Deployment Guide

## Overview

This guide covers deploying MutaLambda in various environments.

## Local Deployment

### Prerequisites
- Python 3.10+
- 8GB RAM minimum
- NVIDIA GPU (optional, for accelerated mode)

### Steps
```bash
# Clone repository
git clone https://github.com/Adlgr87/MutaLambda.git
cd MutaLambda

# Install
bash scripts/install.sh

# Configure
cp config.example.yaml config.yaml
# Edit config.yaml as needed

# Initialize project
mutalambda init --name my_project

# Run
mutalambda run --config config.yaml
```

## Docker Deployment

### Build image
```bash
# CPU-only image (the repository ships a single multi-stage Dockerfile).
docker build -t mutalambda:cpu .
```

> Note: there is no separate `Dockerfile.gpu` in this repository. For GPU
> workloads, build the same image and grant access to the host GPU at runtime
> (see below). A dedicated GPU image is a follow-up, not a maintained path.

### Run container
```bash
# CPU mode (read-only, unprivileged, no network — the image already runs as a
# non-root user uid/gid 10001).
docker run -v $(pwd)/config.yaml:/workspace/config.yaml mutalambda:cpu

# GPU mode (requires nvidia-container-toolkit on the host)
docker run --gpus all -v $(pwd)/config.yaml:/workspace/config.yaml mutalambda:cpu
```

## Kubernetes Deployment

### Manifest
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mutalambda
spec:
  replicas: 3
  selector:
    matchLabels:
      app: mutalambda
  template:
    metadata:
      labels:
        app: mutalambda
    spec:
      containers:
      - name: mutalambda
        image: mutalambda:gpu
        resources:
          limits:
            nvidia.com/gpu: 1
        volumeMounts:
        - name: config
          mountPath: /app/config
      volumes:
      - name: config
        configMap:
          name: mutalambda-config
```

## Cloud Deployment

### AWS
```bash
# Launch EC2 with GPU. Replace <ami-id> with the AMI for your region/account;
# there is no default AMI baked into this guide.
aws ec2 run-instances --instance-type p3.2xlarge --image-id <ami-id>

# Deploy container
aws ecs create-cluster --cluster-name mutalambda
aws ecs register-task-definition --cli-input-json file://task-definition.json
```

### GCP
```bash
# Create GPU instance
gcloud compute instances create mutalambda-gpu \
    --machine-type=n1-standard-8 \
    --accelerator=count=1,type=nvidia-tesla-t4 \
    --image-family=pytorch-gpu \
    --image-project=deeplearning-platform-release
```

## Monitoring

### Health checks
```bash
# Check deployment status
mutalambda status

# View logs
tail -f logs/mutalambda.log

# Check metrics
curl http://localhost:8080/metrics
```

### Alerting
Configure alerts in `.github/workflows/` for:
- Test failures
- Coverage drops below 85%
- Performance degradation

## Rollback

MutaLambda does **not** provide a `scripts/install.sh --rollback` flag. Rollback
is a two-part operation: revert the code and restore a compatible checkpoint.

```bash
# 1. Revert code to a known-good, tagged release (prefer immutable tags/artifacts
#    over bare commits — see "Releases" below).
git checkout <release-tag>
#    or, for a containerized deployment, redeploy the exact immutable image tag
#    (e.g. ghcr.io/adlgr87/mutalambda:<version>).

# 2. Resume from a checkpoint produced by that same version.
mutalambda resume --checkpoint checkpoints/<run-id>.msgpack
```

> Checkpoint compatibility: ``checkpoint_manager.load_checkpoint`` /
> ``resume_agent`` restore state serialized with msgpack and carry a schema
> version. A checkpoint written by a newer version may not restore cleanly on an
> older one — roll back code and checkpoint **together**. Artifacts for a run are
> tracked separately by ``run_artifacts.py``; keep them alongside the checkpoint
> to reproduce results.

## Releases

- Prefer immutable, tagged releases (git tags + pinned image digests) over
  moving refs. The Docker workflow publishes ``ghcr.io/adlgr87/mutalambda:<version>``
  and ``:latest`` on pushes to ``main``.
- Record the version, Python version, image digest and dependency hashes with
  every benchmark artifact so results stay comparable across rollbacks.

## Support

- Documentation: `docs/`
- Issues: GitHub Issues
- Community: [Discord/Slack]
