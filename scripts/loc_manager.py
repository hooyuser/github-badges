import os
import json
import subprocess
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns

# CONFIG
LOC_DIR = "LOC"
DIAGRAM_DIR = "diagrams"
DATE_FORMAT = "%Y-%m-%d"

os.makedirs(LOC_DIR, exist_ok=True)
os.makedirs(DIAGRAM_DIR, exist_ok=True)

def run_command(cmd, cwd="."):
    """Helper to run shell commands"""
    return subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True).stdout.strip()

def get_last_recorded_date(history):
    """Finds the last date recorded in our JSON, or returns None if empty"""
    if not history:
        return None
    return history[-1]["date"]

def get_daily_commits_since(repo_dir, since_date=None):
    """
    Returns a list of (date, sha) tuples for the last commit of every day 
    starting AFTER since_date.
    If since_date is None, returns commits from the beginning of time.
    """
    # Format: Hash Date
    cmd = "git log --reverse --format='%H %cd' --date=format:'%Y-%m-%d'"
    
    # If we have a start date, only look at commits AFTER that date
    if since_date:
        # We add 1 day to since_date to avoid re-processing the same day
        # Note: git log --since is inclusive, so we handle logic carefully below
        cmd += f" --since='{since_date} 23:59:59'"
    
    raw_log = run_command(cmd, cwd=repo_dir)
    if not raw_log:
        return []

    lines = raw_log.split('\n')
    
    # Filter to get only the LAST commit of each unique day
    daily_commits = {} # Key: Date, Value: SHA
    for line in lines:
        parts = line.split(' ')
        sha = parts[0]
        date = parts[1]
        # Since log is reversed (oldest to newest), overwriting the key 
        # naturally keeps the LATEST commit for that date.
        daily_commits[date] = sha
        
    # Convert back to sorted list
    return sorted(daily_commits.items())

def process_repo(repo_name, repo_url, token):
    print(f"--- Processing {repo_name} ---")
    
    # 1. Load Existing History
    json_filename = repo_name.replace("/", "-") + ".json"
    json_path = os.path.join(LOC_DIR, json_filename)
    
    history = []
    if os.path.exists(json_path):
        with open(json_path, 'r') as f:
            history = json.load(f)
            
    last_recorded_date = get_last_recorded_date(history)
    last_recorded_lines = history[-1]["lines"] if history else 0
    
    print(f"Last recorded date: {last_recorded_date if last_recorded_date else 'Never (Full History Mode)'}")

    # 2. Clone Repository (Full History required for time travel)
    # We remove --depth 1 because we need history now
    temp_dir = "temp_repo"
    run_command("rm -rf temp_repo")
    
    # Construct Secure URL
    auth_url = repo_url.replace("https://", f"https://{token}@")
    run_command(f"git clone {auth_url} {temp_dir}")
    
    if not os.path.exists(temp_dir):
        print("Failed to clone.")
        return

    # 3. Get list of commits to process (The "Gap")
    commits_to_process = get_daily_commits_since(temp_dir, last_recorded_date)
    
    if not commits_to_process:
        print("No new commits found since last run.")
    else:
        print(f"Found {len(commits_to_process)} days to backfill/update.")
    
    # 4. Iterate through time
    changes_made = False
    
    for date, sha in commits_to_process:
        # Checkout that specific point in time
        run_command(f"git checkout -q {sha}", cwd=temp_dir)
        
        # Count Lines (Accurate method: Find files -> wc -l)
        # Excludes .git directory
        count_cmd = "find . -type f -not -path '*/.git/*' | xargs wc -l | tail -n 1 | awk '{print $1}'"
        try:
            current_lines = int(run_command(count_cmd, cwd=temp_dir))
        except:
            current_lines = 0
            
        # SPARSE LOGIC: 
        # If lines changed compared to the LAST recorded value, save it.
        # OR if it's the very first entry.
        if current_lines != last_recorded_lines:
            print(f"[{date}] Change detected: {last_recorded_lines} -> {current_lines}")
            history.append({"date": date, "lines": current_lines})
            last_recorded_lines = current_lines
            changes_made = True
        else:
            # Redundant day (LOC didn't change), skip storing
            pass

    # 5. Cleanup
    run_command("rm -rf temp_repo")

    # 6. Save JSON (Only if changes happened)
    if changes_made:
        with open(json_path, 'w') as f:
            json.dump(history, f, indent=2)
        print("History updated.")
        
    # 7. Always regenerate diagram (to ensure it looks fresh)
    generate_svg(repo_name, history)

def generate_svg(repo_name, history):
    if not history: return

    dates = [datetime.strptime(d["date"], DATE_FORMAT) for d in history]
    lines = [d["lines"] for d in history]

    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(10, 5))
    
    # 'steps-post' draws the line horizontally until the next change
    # This perfectly visualizes "Sparse" data
    ax.plot(dates, lines, color='#00f2ff', linewidth=2, marker='.', markersize=5, drawstyle='steps-post')
    ax.fill_between(dates, lines, alpha=0.1, color='#00f2ff', step='post')

    ax.set_title(f"Lines of Code: {repo_name}", fontsize=14, fontweight='bold', color='white')
    ax.grid(True, linestyle='--', alpha=0.15)
    
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.xticks(rotation=45)
    
    output_filename = repo_name.replace("/", "-") + ".svg"
    plt.tight_layout()
    plt.savefig(os.path.join(DIAGRAM_DIR, output_filename), format='svg', transparent=True)
    plt.close()

if __name__ == "__main__":
    repos = os.environ.get("REPOS", "").split()
    token = os.environ.get("GH_TOKEN")
    
    for repo in repos:
        process_repo(repo, f"https://github.com/{repo}.git", token)
