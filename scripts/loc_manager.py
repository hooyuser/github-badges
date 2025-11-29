import os
import json
import subprocess
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# --- CONFIGURATION ---
LOC_DIR = "LOC"            # Stores history (sparse)
BADGE_DIR = "badges"       # Stores current status (for Shields.io)
DIAGRAM_DIR = "diagrams"   # Stores SVG graphs
DATE_FORMAT = "%Y-%m-%d"

# Ensure directories exist
os.makedirs(LOC_DIR, exist_ok=True)
os.makedirs(BADGE_DIR, exist_ok=True)
os.makedirs(DIAGRAM_DIR, exist_ok=True)

def run_command(cmd, cwd="."):
    """Helper to run shell commands safely"""
    try:
        result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
        return result.stdout.strip()
    except Exception as e:
        print(f"Error running command '{cmd}': {e}")
        return ""

def format_number(lines):
    """
    REGRESSION PROOFING: Matches the exact bash logic for 3.5k / 1.2M
    """
    if lines > 1000000:
        return f"{lines / 1000000:.1f}M"
    elif lines > 1000:
        return f"{lines / 1000:.1f}k"
    else:
        return str(lines)

def get_last_recorded_date(history):
    if not history: return None
    return history[-1]["date"]

def get_daily_commits_since(repo_dir, since_date=None):
    """Returns list of (date, sha) for the last commit of every day after since_date"""
    cmd = "git log --reverse --format='%H %cd' --date=format:'%Y-%m-%d'"
    if since_date:
        cmd += f" --since='{since_date} 23:59:59'"
    
    raw_log = run_command(cmd, cwd=repo_dir)
    if not raw_log: return []

    lines = raw_log.split('\n')
    daily_commits = {}
    for line in lines:
        parts = line.split(' ')
        if len(parts) >= 2:
            daily_commits[parts[1]] = parts[0] # Date -> SHA
            
    return sorted(daily_commits.items())

def count_lines_at_commit(repo_dir, sha=None):
    """
    Counts lines using the find+wc method (most accurate for all languages)
    """
    if sha:
        run_command(f"git checkout -q {sha}", cwd=repo_dir)
        
    # Exclude .git directory, count all files
    cmd = "find . -type f -not -path '*/.git/*' | xargs wc -l | tail -n 1 | awk '{print $1}'"
    try:
        return int(run_command(cmd, cwd=repo_dir))
    except:
        return 0

def generate_simple_badge(repo_name, current_lines):
    """
    REGRESSION PROOFING: Generates the exact JSON for Shields.io
    matches: badges/hooyuser-algebraic_geometry.json
    """
    formatted = format_number(current_lines)
    filename = repo_name.replace("/", "-") + ".json"
    filepath = os.path.join(BADGE_DIR, filename)
    
    data = {
        "schemaVersion": 1,
        "label": "Lines of Code",
        "message": formatted,
        "color": "blue"
    }
    
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"   [Badge Updated] {formatted}")

def process_repo(repo_name, repo_url, token):
    print(f"\n--- Processing {repo_name} ---")
    
    # 1. Setup History File
    json_filename = repo_name.replace("/", "-") + ".json"
    history_path = os.path.join(LOC_DIR, json_filename)
    
    history = []
    if os.path.exists(history_path):
        with open(history_path, 'r') as f:
            history = json.load(f)

    last_date = get_last_recorded_date(history)
    last_lines = history[-1]["lines"] if history else 0

    # 2. Clone Repo
    temp_dir = "temp_repo"
    run_command("rm -rf temp_repo")
    auth_url = repo_url.replace("https://", f"https://{token}@")
    run_command(f"git clone {auth_url} {temp_dir}")
    
    if not os.path.exists(temp_dir):
        print(f"!!! Failed to clone {repo_name}")
        return

    # 3. Time Travel (Incremental Backfill)
    commits = get_daily_commits_since(temp_dir, last_date)
    changes_made = False
    current_lines = last_lines # Default if no new commits

    if commits:
        print(f"   Found {len(commits)} days to process...")
        for date, sha in commits:
            lines = count_lines_at_commit(temp_dir, sha)
            current_lines = lines # Update current status
            
            # Sparse Logic: Only save history if changed
            if lines != last_lines:
                history.append({"date": date, "lines": lines})
                last_lines = lines
                changes_made = True
    else:
        # If no new commits, we still need current count for the badge
        # (It might be the same as history, but we verify)
        current_lines = count_lines_at_commit(temp_dir, None)

    # 4. Save History (If changed)
    if changes_made:
        with open(history_path, 'w') as f:
            json.dump(history, f, indent=2)
            
    # 5. [CRITICAL] Always Generate the Simple Badge (The Regression Fix)
    generate_simple_badge(repo_name, current_lines)

    # 6. Generate SVG Graph
    generate_svg(repo_name, history)
    
    # Cleanup
    run_command("rm -rf temp_repo")

def generate_svg(repo_name, history):
    if not history: return
    
    dates = [datetime.strptime(d["date"], DATE_FORMAT) for d in history]
    lines = [d["lines"] for d in history]

    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(10, 5))
    
    # Draw logic
    ax.plot(dates, lines, color='#00f2ff', linewidth=2, marker='.', markersize=0, drawstyle='steps-post')
    ax.fill_between(dates, lines, alpha=0.15, color='#00f2ff', step='post')

    # Titles
    ax.set_title(f"Lines of Code: {repo_name}", fontsize=14, fontweight='bold', color='white')
    ax.grid(True, linestyle='--', alpha=0.1)
    
    # Formatting
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.xticks(rotation=45)
    
    # Save
    filename = repo_name.replace("/", "-") + ".svg"
    output_path = os.path.join(DIAGRAM_DIR, filename)
    plt.tight_layout()
    plt.savefig(output_path, format='svg', transparent=True)
    plt.close()

if __name__ == "__main__":
    # Load Repos from file
    repos = []
    if os.path.exists("repos.txt"):
        with open("repos.txt", "r") as f:
            repos = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    
    token = os.environ.get("GH_TOKEN")
    
    if not repos:
        print("No repos found in repos.txt")
    
    for repo in repos:
        process_repo(repo, f"https://github.com/{repo}.git", token)
