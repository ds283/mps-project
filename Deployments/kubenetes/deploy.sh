#!/bin/bash

echo "Creating volumes..."

kubectl apply -f ./k8s-manifests/pv-assets.yml
kubectl apply -f ./k8s-manifests/pv-backups.yml
kubectl apply -f ./k8s-manifests/pv-instance.yml
kubectl apply -f ./k8s-manifests/pv-logs.yml
kubectl apply -f ./k8s-manifests/pv-mariadb-data.yml
kubectl apply -f ./k8s-manifests/pv-mongodb-data.yml
kubectl apply -f ./k8s-manifests/pv-profiling.yml

echo "Creating volume claims..."

kubectl apply -f ./k8s-manifests/pvc-assets.yml
kubectl apply -f ./k8s-manifests/pvc-backups.yml
kubectl apply -f ./k8s-manifests/pvc-instance.yml
kubectl apply -f ./k8s-manifests/pvc-logs.yml
kubectl apply -f ./k8s-manifests/pvc-mariadb-data.yml
kubectl apply -f ./k8s-manifests/pvc-mongodb-data.yml
kubectl apply -f ./k8s-manifests/pvc-profiling.yml

echo "Creating MariaDB credentials..."

kubectl apply -f ./k8s-manifests/secrets/secrets-mariadb.yml

echo "Creating MongoDB credentials..."

kubectl apply -f ./k8s-manifests/secrets/secrets-mongodb.yml

echo "Creating NGINX credentials..."

kubectl apply -f ./k8s-manifests/secrets/secrets-nginx.yml

echo "Creating MariaDB ConfigMaps..."

kubectl apply -f ./k8s-manifests/configmap-mariadb.yml

echo "Creating MariaDB deployment and service..."

kubectl apply -f ./k8s-manifests/deploy-mariadb.yml
kubectl apply -f ./k8s-manifests/service-mariadb.yml

echo "Creating MongoDB deployment and service..."

kubectl apply -f ./k8s-manifests/deploy-mongodb.yml
kubectl apply -f ./k8s-manifests/service-mongodb.yml

echo "Creating redis deployment and service..."

kubectl apply -f ./k8s-manifests/deploy-redis.yml
kubectl apply -f ./k8s-manifests/service-redis.yml

echo "Creating webapp deployment, service, and autoscaler..."

kubectl apply -f ./k8s-manifests/deploy-app.yml
kubectl apply -f ./k8s-manifests/service-app.yml

kubectl apply -f ./k8s-manifests/autoscale-app.yml

echo "Creating Celery worker queue deployments and autoscaler..."

kubectl apply -f ./k8s-manifests/deploy-default-worker.yml
kubectl apply -f ./k8s-manifests/deploy-priority-worker.yml

kubectl apply -f ./k8s-manifests/autoscale-default-worker.yml

echo "Creating Celery services (scheduler, flower)..."

kubectl apply -f ./k8s-manifests/deploy-celery-scheduler.yml
kubectl apply -f ./k8s-manifests/deploy-celery-dashboard.yml

kubectl apply -f ./k8s-manifests/service-celery-dashboard.yml

echo "Creating NGINX Ingress Controller and routing rules..."

kubectl apply -f ./k8s-manifests/ingress-default.yml
kubectl apply -f ./k8s-manifests/deploy-ingress-nginx.yml
