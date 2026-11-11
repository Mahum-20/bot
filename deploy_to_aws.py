import os
import sys
import subprocess
import argparse

KEY_PATH = r"C:\Users\PMLS\Downloads\LightsailDefaultKey-ap-northeast-1.pem"
DEFAULT_HOST = "13.230.185.230"
ALT_HOST = "54.238.45.182"
DUCKDNS_HOST = "mayhembot.duckdns.org"

BACKEND_FILES = [
    "htf_engine.py",
    "ltf_approach_engine.py",
    "mtf_strategy.py",
    "server.py",
    "main.py",
    "pattern_scanner.py",
    "binance_feed.py",
    "binance_live_executor.py",
    "portfolio_risk_manager.py",
    "timeframe_allocation_manager.py",
    "canonical_strategy_engine.py",
    "zone_trade_registry.py",
    "htf_level_lifecycle_manager.py",
    "exchange_filter_manager.py",
    "rule_traceability_logger.py",
    "faithful_backtest_engine.py",
    "bot_config.json"
]

def run_cmd(cmd, check=True):
    print(f"\n[EXEC] {cmd}")
    res = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if res.stdout:
        print(res.stdout)
    if res.stderr:
        print(f"[STDERR] {res.stderr}")
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed with code {res.returncode}")
    return res

def test_connection(host):
    print(f"Testing SSH connectivity to {host}...")
    cmd = f'ssh -i "{KEY_PATH}" -o StrictHostKeyChecking=no -o ConnectTimeout=6 ubuntu@{host} "echo SSH_CONNECTED"'
    res = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if "SSH_CONNECTED" in res.stdout:
        print(f"[SUCCESS] SSH connection to {host} succeeded!")
        return True
    return False

def deploy(host):
    print(f"\n=== Deploying backend updates to AWS: ubuntu@{host} ===")
    print("NOTE: Dashboard static files are strictly UNTOUCHED as requested.\n")

    # 0. Local file integrity check
    print("\n0. Verifying local files...")
    for f in BACKEND_FILES:
        if not os.path.exists(f):
            raise FileNotFoundError(f"Missing required deployment file: {f}")
    print("[SUCCESS] All backend deployment files verified locally.")

    # 1. Test connection
    if not test_connection(host):
        print(f"[ERROR] Could not connect to {host}. Please check if the AWS instance is running or if the IP changed.")
        return False

    # 2. Backup existing remote code
    print("\n1. Creating remote backup...")
    backup_cmd = f'ssh -i "{KEY_PATH}" -o StrictHostKeyChecking=no ubuntu@{host} "mkdir -p /home/ubuntu/backups && cp -r /home/ubuntu/bot /home/ubuntu/backups/bot_backup_$(date +%Y%m%d_%H%M%S) 2>/dev/null || true"'
    run_cmd(backup_cmd, check=False)

    # 3. Upload backend python files
    print("\n2. Uploading updated backend engine files...")
    files_str = " ".join(BACKEND_FILES)
    scp_cmd = f'scp -i "{KEY_PATH}" -o StrictHostKeyChecking=no {files_str} ubuntu@{host}:/home/ubuntu/bot/'
    run_cmd(scp_cmd)

    # 4. Upload updated registry
    if os.path.exists("data/zone_trades_registry.json"):
        print("\n3. Syncing zone trades registry...")
        scp_reg = f'scp -i "{KEY_PATH}" -o StrictHostKeyChecking=no data/zone_trades_registry.json ubuntu@{host}:/home/ubuntu/bot/data/'
        run_cmd(scp_reg, check=False)

    # 5. Pre-deployment remote import verification
    print("\n4. Verifying Python module imports on AWS before restart...")
    verify_cmd = f'ssh -i "{KEY_PATH}" -o StrictHostKeyChecking=no ubuntu@{host} "cd /home/ubuntu/bot && python3 -c \"import server; import zone_trade_registry; import canonical_strategy_engine; print(\'REMOTE_VERIFICATION_PASSED\')\""'
    ver_res = subprocess.run(verify_cmd, shell=True, text=True, capture_output=True)
    if "REMOTE_VERIFICATION_PASSED" not in ver_res.stdout:
        print(f"[CRITICAL ERROR] Remote import verification failed!\nSTDOUT: {ver_res.stdout}\nSTDERR: {ver_res.stderr}")
        raise RuntimeError("Aborting restart: remote imports or configuration failed verification.")
    print("[SUCCESS] Remote Python modules verified cleanly.")

    # 6. Restart trading-bot service
    print("\n5. Restarting trading-bot service on AWS...")
    restart_cmd = f'ssh -i "{KEY_PATH}" -o StrictHostKeyChecking=no ubuntu@{host} "sudo systemctl restart trading-bot && sleep 2 && systemctl is-active trading-bot"'
    res = run_cmd(restart_cmd)

    # 6. Verify service status
    print("\n5. Checking service status...")
    status_cmd = f'ssh -i "{KEY_PATH}" -o StrictHostKeyChecking=no ubuntu@{host} "systemctl status trading-bot --no-pager -l | head -n 20"'
    run_cmd(status_cmd, check=False)

    print("\n[COMPLETE] Deployment to AWS completed successfully!")
    return True

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    if target:
        deploy(target)
    else:
        # Try known hosts
        for h in [DUCKDNS_HOST, DEFAULT_HOST, ALT_HOST]:
            if test_connection(h):
                deploy(h)
                sys.exit(0)
        print("\n[NOTICE] None of the previous IPs/hostnames (mayhembot.duckdns.org, 13.230.185.230, 54.238.45.182) responded.")
        print("Please check if the AWS Lightsail/EC2 instance is running, or provide its current Public IP address.")
        sys.exit(1)
