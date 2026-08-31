#!/bin/bash
set -euo pipefail

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
    cat <<'EOF'
Usage:
  ./scripts/deploy_to_robot.sh <user@robot-host> [remote_target_dir]

Examples:
  ./scripts/deploy_to_robot.sh qtrobot@192.168.100.10
  ./scripts/deploy_to_robot.sh qtrobot@192.168.100.10 ~/robot/code/tutorials/QT_ai_assistant
  ROBOT_HOST=192.168.100.10 ROBOT_USER=qtrobot ./scripts/deploy_to_robot.sh

Optional environment variables:
  ROBOT_HOST                 Robot body computer IP/hostname.
  ROBOT_USER                 SSH user. Defaults to qtrobot when ROBOT_HOST is used.
  ROBOT_TARGET_DIR           Remote target dir. Defaults to ~/robot/code/tutorials/QT_ai_assistant.
  DEPLOY_DRY_RUN=true        Show what would be uploaded without copying.
  DEPLOY_DELETE=true         Delete remote files that no longer exist locally.
  DEPLOY_INCLUDE_LOCAL_ENV=true
                             Also upload local .env files. Default is false.
  DEPLOY_DISABLE_YBC_MODEL=true
                             Set ECG_YBC_MODEL_ENABLED=false in the robot's
                             existing ECG config without replacing other values.
  DEPLOY_SSH_OPTS="-p 22"    Extra ssh options.
EOF
}

REMOTE="${1:-}"
if [ -z "$REMOTE" ] && [ -n "${ROBOT_HOST:-}" ]; then
    REMOTE="${ROBOT_USER:-qtrobot}@${ROBOT_HOST}"
fi

if [ "${REMOTE:-}" = "-h" ] || [ "${REMOTE:-}" = "--help" ]; then
    usage
    exit 0
fi

if [ -z "$REMOTE" ]; then
    usage
    exit 1
fi

if [[ "$REMOTE" != *@* ]]; then
    REMOTE="${ROBOT_USER:-qtrobot}@$REMOTE"
fi

TARGET_DIR="${2:-${ROBOT_TARGET_DIR:-~/robot/code/tutorials/QT_ai_assistant}}"
DEPLOY_DRY_RUN="${DEPLOY_DRY_RUN:-false}"
DEPLOY_DELETE="${DEPLOY_DELETE:-false}"
DEPLOY_INCLUDE_LOCAL_ENV="${DEPLOY_INCLUDE_LOCAL_ENV:-false}"
DEPLOY_DISABLE_YBC_MODEL="${DEPLOY_DISABLE_YBC_MODEL:-false}"
DEPLOY_SSH_OPTS="${DEPLOY_SSH_OPTS:-}"

if ! command -v rsync >/dev/null 2>&1; then
    echo "ERROR: rsync is required for deployment."
    exit 127
fi

RSYNC_ARGS=(
    -az
    --human-readable
    --info=stats2,progress2
)

if [ -n "$DEPLOY_SSH_OPTS" ]; then
    RSYNC_ARGS+=(-e "ssh $DEPLOY_SSH_OPTS")
fi

if [ "$DEPLOY_DRY_RUN" = "true" ]; then
    RSYNC_ARGS+=(--dry-run)
fi

if [ "$DEPLOY_DELETE" = "true" ]; then
    RSYNC_ARGS+=(--delete)
fi

EXCLUDES=(
    --exclude=.git/
    --exclude=.agents/
    --exclude=.codex/
    --exclude=.vscode/
    --exclude=.idea/
    --exclude=.DS_Store
    --exclude=._*
    --exclude=.firebase/
    --exclude=__pycache__/
    --exclude='*.pyc'
    --exclude='*.pyo'
    --exclude='*.log'
    --exclude=.venv/
    --exclude=venv/
    --exclude=env/
    --exclude=ENV/
    --exclude=logs/
    --exclude=runtime/
    --exclude=.langgraph_state/
    --exclude=.langgraph_api/
    --exclude=ai/.langgraph_api/
    --exclude='*.sqlite3'
    --exclude=build/
    --exclude=devel/
    --exclude=install/
    --exclude=log/
    --exclude='*build*/'
    --exclude='*devel*/'
    --exclude='*install*/'
    --exclude=ecg/src/SDM_DEMO_GUI/
    --exclude=ecg/src/ybc/lib/
    --exclude=secret/
    --exclude=keys/
    --exclude='*.key'
    --exclude=credentials.json
)

if [ "$DEPLOY_INCLUDE_LOCAL_ENV" != "true" ]; then
    EXCLUDES+=(
        --exclude=.env
        --exclude=ai/config/.env
        --exclude=config/ecg_integration.env
    )
fi

SSH_CMD=(ssh)
if [ -n "$DEPLOY_SSH_OPTS" ]; then
    # shellcheck disable=SC2206
    SSH_CMD+=( $DEPLOY_SSH_OPTS )
fi

echo "========================================="
echo " Deploy qt_ai_assistant to robot"
echo "========================================="
echo "local:  $WORKSPACE_DIR/"
echo "remote: $REMOTE:$TARGET_DIR/"
echo "dry_run=$DEPLOY_DRY_RUN delete=$DEPLOY_DELETE include_env=$DEPLOY_INCLUDE_LOCAL_ENV disable_ybc=$DEPLOY_DISABLE_YBC_MODEL"
echo "========================================="

if [ "$DEPLOY_DRY_RUN" != "true" ]; then
    "${SSH_CMD[@]}" "$REMOTE" "mkdir -p $TARGET_DIR"
fi

rsync "${RSYNC_ARGS[@]}" "${EXCLUDES[@]}" "$WORKSPACE_DIR/" "$REMOTE:$TARGET_DIR/"

if [ "$DEPLOY_DRY_RUN" = "true" ]; then
    echo "Dry run complete. No files were uploaded."
    exit 0
fi

"${SSH_CMD[@]}" "$REMOTE" "
    mkdir -p $TARGET_DIR/runtime $TARGET_DIR/logs
    cd $TARGET_DIR
    chmod +x scripts/*.sh
    if [ ! -f config/ecg_integration.env ] && [ -f config/ecg_integration.env.example ]; then
        cp config/ecg_integration.env.example config/ecg_integration.env
    fi
    if [ '$DEPLOY_DISABLE_YBC_MODEL' = 'true' ]; then
        if grep -q '^ECG_YBC_MODEL_ENABLED=' config/ecg_integration.env; then
            sed -i 's/^ECG_YBC_MODEL_ENABLED=.*/ECG_YBC_MODEL_ENABLED=false/' config/ecg_integration.env
        else
            printf '\nECG_YBC_MODEL_ENABLED=false\n' >> config/ecg_integration.env
        fi
    fi
"

echo "========================================="
echo "Deploy complete."
echo "Next on robot:"
echo "  ssh $REMOTE"
echo "  cd $TARGET_DIR"
echo "  nano config/ecg_integration.env"
echo "  nano ai/config/.env"
echo "  ./scripts/run.sh"
echo "========================================="
