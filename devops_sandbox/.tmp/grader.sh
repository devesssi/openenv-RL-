#!/bin/bash
set -m

pkill -f "node server.js" 2>/dev/null
sleep 0.5

cd E:\programs2\openenv(RL)\devops_sandbox\.app_sandbox
node server.js > E:\programs2\openenv(RL)\devops_sandbox\.tmp/node.log 2>&1 &
NODE_PID=$!

for i in 1 2 3 4; do
  sleep 1
  if curl -s http://localhost:3000/health > /dev/null 2>&1; then
    break
  fi
done

STARTUP_LOG=$(cat E:\programs2\openenv(RL)\devops_sandbox\.tmp/node.log 2>/dev/null)

HEALTH_CODE=$(curl -s -o E:\programs2\openenv(RL)\devops_sandbox\.tmp/health.json -w '%{http_code}' http://localhost:3000/health 2>/dev/null)
USERS_CODE=$(curl -s -o E:\programs2\openenv(RL)\devops_sandbox\.tmp/users.json -w '%{http_code}' http://localhost:3000/api/users 2>/dev/null)
DATA_CODE=$(curl -s -o E:\programs2\openenv(RL)\devops_sandbox\.tmp/data.json -w '%{http_code}' http://localhost:3000/api/data 2>/dev/null)
USERS_BODY=$(cat E:\programs2\openenv(RL)\devops_sandbox\.tmp/users.json 2>/dev/null)
DATA_BODY=$(cat E:\programs2\openenv(RL)\devops_sandbox\.tmp/data.json 2>/dev/null)

kill $NODE_PID 2>/dev/null
wait $NODE_PID 2>/dev/null

echo "GRADER_STARTUP_LOG:${STARTUP_LOG}"
echo "GRADER_HEALTH_CODE:${HEALTH_CODE}"
echo "GRADER_USERS_CODE:${USERS_CODE}"
echo "GRADER_DATA_CODE:${DATA_CODE}"
echo "GRADER_USERS_BODY:${USERS_BODY}"
echo "GRADER_DATA_BODY:${DATA_BODY}"
