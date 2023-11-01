#!/bin/bash

# This script creates backup buckets on Exoscale in ch-dk-2 zone
# in <namespace> with <prefix name> and <amount> of buckets
# Usage: ./bucket-creation.sh <prefix name> <namespace> <amount>

set -e

PREFIX_NAME=$1
NAMESPACE=$2
DAYS=$3

for (( i = 1; i <= DAYS; i++ )); do
   echo $i
   DESTINATION_BUCKET="backup-${PREFIX_NAME}-$i";
   echo "Creating bucket " $DESTINATION_BUCKET
   kubectl apply --as cluster-admin -f - <<EOF
      apiVersion: appcat.vshn.io/v1
      kind: ObjectBucket
      metadata:
        name: $DESTINATION_BUCKET
        namespace: $NAMESPACE
      spec:
        parameters:
          bucketDeletionPolicy: DeleteIfEmpty
          bucketName: $DESTINATION_BUCKET
          region: ch-dk-2
          bucketDeletionPolicy: DeleteIfEmpty
        writeConnectionSecretToRef:
          name: $DESTINATION_BUCKET-credentials
EOF
done
