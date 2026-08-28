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
# CPU-only image
docker build -t mutalambda:cpu .

# GPU-enabled image
docker build -f Dockerfile.gpu -t mutalambda:gpu .
```

### Run container
```bash
# CPU mode
docker run -v $(pwd)/config.yaml:/app/config.yaml mutalambda:cpu

# GPU mode
docker run --gpus all -v $(pwd)/config.yaml:/app/config.yaml mutalambda:gpu
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
# Launch EC2 with GPU
aws ec2 run-instances --instance-type p3.2xlarge --image-id ami-xxx

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

```bash
# Rollback to previous version
git checkout <previous-commit>
bash scripts/install.sh --rollback
```

## Support

- Documentation: `docs/`
- Issues: GitHub Issues
- Community: [Discord/Slack]
