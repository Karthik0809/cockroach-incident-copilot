#!/usr/bin/env bash
# Build the demo UI, push to ECR, and roll out on ECS Fargate.
#
#   AWS_ACCOUNT_ID=123456789012 AWS_REGION=us-east-1 ./infra/deploy-ui.sh
#
# Prerequisites (one time):
#   - ECR repo:        aws ecr create-repository --repository-name incident-copilot
#   - Secret:          aws secretsmanager create-secret \
#                        --name incident-copilot/database-url \
#                        --secret-string "$DATABASE_URL"
#   - ECS cluster + service fronted by an ALB on port 8501
#   - Task role with bedrock:InvokeModel

set -euo pipefail

: "${AWS_ACCOUNT_ID:?set AWS_ACCOUNT_ID}"
: "${AWS_REGION:=us-east-1}"

REPO="incident-copilot"
CLUSTER="${ECS_CLUSTER:-incident-copilot}"
SERVICE="${ECS_SERVICE:-incident-copilot-ui}"
REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
TAG="$(git rev-parse --short HEAD)"

echo "==> authenticating to ECR"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

echo "==> building ${REPO}:${TAG}"
docker build --platform linux/amd64 -t "${REPO}:${TAG}" .
docker tag "${REPO}:${TAG}" "${REGISTRY}/${REPO}:${TAG}"
docker tag "${REPO}:${TAG}" "${REGISTRY}/${REPO}:latest"

echo "==> pushing"
docker push "${REGISTRY}/${REPO}:${TAG}"
docker push "${REGISTRY}/${REPO}:latest"

echo "==> registering task definition"
sed -e "s/ACCOUNT_ID/${AWS_ACCOUNT_ID}/g" \
    -e "s/REGION/${AWS_REGION}/g" \
    -e "s|:latest|:${TAG}|g" \
    infra/ecs-task-definition.json > /tmp/task-def.json

TASK_ARN="$(aws ecs register-task-definition \
  --cli-input-json file:///tmp/task-def.json \
  --region "$AWS_REGION" \
  --query 'taskDefinition.taskDefinitionArn' --output text)"

echo "==> rolling out ${TASK_ARN}"
aws ecs update-service \
  --cluster "$CLUSTER" \
  --service "$SERVICE" \
  --task-definition "$TASK_ARN" \
  --force-new-deployment \
  --region "$AWS_REGION" \
  --query 'service.deployments[0].{status:rolloutState,desired:desiredCount}'

echo "==> waiting for the service to stabilize"
aws ecs wait services-stable \
  --cluster "$CLUSTER" --services "$SERVICE" --region "$AWS_REGION"

echo "done. UI is live behind the ALB."
