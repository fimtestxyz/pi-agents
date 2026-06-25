#!/usr/bin/env python3
"""
Pi Agent Cluster Concurrent Load Test.
Sends chat requests to all running agents in parallel,
measures per-agent and average response times.
"""

import http.client
import json
import os
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Colors
BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
NC = "\033[0m"

# Test prompts — varied lengths to stress different inference paths
TEST_PROMPTS = [
    "Say hello in 5 words.",
    "What is 2+2? Answer with just the number.",
    "Name three primary colors.",
    "What is the capital of France? One word answer.",
    "Count from 1 to 5.",
]

MODELS_CONFIG_PATH = os.getenv("MODELS_CONFIG_PATH", "/home/pi/.pi/agent/models.json")


def detect_agents():
    """Probe Docker for running pi-agent containers."""
    agents = {}
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            capture_output=True, text=True, timeout=10,
        )
        text = result.stdout.strip()
        if not text:
            return agents

        containers = []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                containers = parsed
            else:
                containers = [parsed]
        except json.JSONDecodeError:
            for line in text.splitlines():
                try:
                    containers.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue

        for c in containers:
            name = c.get("Name", c.get("name", ""))
            if not name.startswith("pi-agent-"):
                continue
            state = c.get("State", c.get("state", "")).lower()
            status = c.get("Status", c.get("status", "")).lower()
            health = c.get("Health", c.get("health", "")).lower()
            try:
                agent_num = int(name.split("-")[-1])
            except ValueError:
                continue
            port = 8000 + agent_num
            is_healthy = state == "running" and (
                "healthy" in status or health == "healthy"
            )
            agents[agent_num] = {
                "name": name,
                "port": port,
                "healthy": is_healthy,
                "status": status,
            }
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: port scan
    if not agents:
        for port in range(8001, 8011):
            try:
                conn = http.client.HTTPConnection("localhost", port, timeout=2)
                conn.request("GET", "/health")
                resp = conn.getresponse()
                if resp.status == 200:
                    agents[port - 8000] = {
                        "name": f"pi-agent-{port - 8000}",
                        "port": port,
                        "healthy": True,
                        "status": "healthy",
                    }
                conn.close()
            except Exception:
                pass

    return agents


def send_request(agent_num, port, prompt, model="gemma4-local", timeout=120):
    """Send a single chat completion request and measure response time."""
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    })
    headers = {"Content-Type": "application/json"}

    start = time.monotonic()
    try:
        conn = http.client.HTTPConnection("localhost", port, timeout=timeout)
        conn.request("POST", "/v1/chat/completions", body=payload, headers=headers)
        resp = conn.getresponse()
        body = resp.read().decode()
        elapsed = time.monotonic() - start

        if resp.status != 200:
            return {
                "agent": agent_num,
                "port": port,
                "prompt": prompt,
                "success": False,
                "error": f"HTTP {resp.status}: {body[:200]}",
                "elapsed": elapsed,
            }

        data = json.loads(body)
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return {
            "agent": agent_num,
            "port": port,
            "prompt": prompt,
            "success": True,
            "content": content[:100],  # truncate for display
            "elapsed": elapsed,
            "tokens": usage.get("total_tokens", 0),
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
        }
    except Exception as e:
        elapsed = time.monotonic() - start
        return {
            "agent": agent_num,
            "port": port,
            "prompt": prompt,
            "success": False,
            "error": str(e),
            "elapsed": elapsed,
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass


def run_concurrent_test(agents, num_rounds=3, max_workers=None):
    """
    Send requests to all agents concurrently.
    Each agent receives each test prompt once per round.
    """
    healthy_agents = {n: a for n, a in agents.items() if a["healthy"]}
    if not healthy_agents:
        print(f"{RED}No healthy agents to test!{NC}")
        return

    all_tasks = []
    task_id = 0

    for round_num in range(1, num_rounds + 1):
        for agent_num, agent_info in sorted(healthy_agents.items()):
            for prompt in TEST_PROMPTS:
                task_id += 1
                all_tasks.append({
                    "id": task_id,
                    "round": round_num,
                    "agent_num": agent_num,
                    "port": agent_info["port"],
                    "prompt": prompt,
                })

    total_tasks = len(all_tasks)
    print(f"\n{BOLD}Launching concurrent load test...{NC}")
    print(f"  Agents:     {len(healthy_agents)}")
    print(f"  Rounds:     {num_rounds}")
    print(f"  Prompts:    {len(TEST_PROMPTS)} per agent per round")
    print(f"  Total:      {total_tasks} requests")
    print(f"  Workers:    {max_workers or 'unlimited (per-agent)'}")
    print(f"{BLUE}--------------------------------------------------{NC}")

    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_map = {}
        for t in all_tasks:
            future = executor.submit(
                send_request, t["agent_num"], t["port"], t["prompt"]
            )
            future_map[future] = t

        # Collect results as they complete
        done_count = 0
        for future in as_completed(future_map):
            done_count += 1
            t = future_map[future]
            result = future.result()
            result["round"] = t["round"]
            results.append(result)

            status = f"{GREEN}✓{NC}" if result["success"] else f"{RED}✗{NC}"
            print(
                f"  {status} [{done_count}/{total_tasks}] "
                f"Agent {result['agent']} R{result['round']} "
                f"{result['elapsed']:.2f}s"
                + (f" ({result.get('completion_tokens', 0)} tok)" if result["success"] else f" ERR: {result.get('error', '')[:50]}")
            )

    return results


def print_report(results, agents):
    """Print a summary report with per-agent and overall stats."""
    print(f"\n{BLUE}--------------------------------------------------{NC}")
    print(f"{BOLD}                   TEST REPORT{NC}")
    print(f"{BLUE}--------------------------------------------------{NC}")

    # Per-agent breakdown
    healthy_agents = {n: a for n, a in agents.items() if a["healthy"]}
    per_agent = {}
    for r in results:
        n = r["agent"]
        if n not in per_agent:
            per_agent[n] = {"times": [], "tokens": [], "successes": 0, "failures": 0}
        per_agent[n]["times"].append(r["elapsed"])
        if r["success"]:
            per_agent[n]["successes"] += 1
            per_agent[n]["tokens"].append(r.get("completion_tokens", 0))
        else:
            per_agent[n]["failures"] += 1

    print(f"\n{BOLD}Per-Agent Statistics:{NC}")
    print(f"{'Agent':<14} {'Requests':<12} {'Success':<10} {'Failed':<8} {'Avg (s)':<10} {'Min (s)':<10} {'Max (s)':<10} {'P95 (s)':<10} {'Avg Tok/s':<10}")
    print("-" * 104)

    all_times = []
    all_tokens_per_sec = []

    for agent_num in sorted(per_agent):
        stats = per_agent[agent_num]
        times = stats["times"]
        successes = stats["successes"]
        failures = stats["failures"]
        total_reqs = successes + failures

        avg_time = statistics.mean(times) if times else 0
        min_time = min(times) if times else 0
        max_time = max(times) if times else 0
        p95_time = sorted(times)[int(len(times) * 0.95)] if len(times) > 1 else max_time

        # Tokens per second (production rate)
        avg_tokens = statistics.mean(stats["tokens"]) if stats["tokens"] else 0
        avg_tok_per_sec = avg_tokens / avg_time if avg_time > 0 else 0

        all_times.extend(times)
        if avg_tok_per_sec > 0:
            all_tokens_per_sec.append(avg_tok_per_sec)

        health_badge = f"{GREEN}●{NC}" if agent_num in healthy_agents else f"{RED}○{NC}"
        print(
            f"{health_badge} Agent {agent_num:<5} "
            f"{total_reqs:<12} {successes:<10} {failures:<8} "
            f"{avg_time:<10.2f} {min_time:<10.2f} {max_time:<10.2f} {p95_time:<10.2f} "
            f"{avg_tok_per_sec:<10.1f}"
        )

    # Overall summary
    print(f"\n{BOLD}Overall Summary:{NC}")
    total_success = sum(s["successes"] for s in per_agent.values())
    total_failure = sum(s["failures"] for s in per_agent.values())
    total_requests = total_success + total_failure
    success_rate = (total_success / total_requests * 100) if total_requests > 0 else 0

    if all_times:
        overall_avg = statistics.mean(all_times)
        overall_min = min(all_times)
        overall_max = max(all_times)
        overall_median = statistics.median(all_times)
        overall_p95 = sorted(all_times)[int(len(all_times) * 0.95)] if len(all_times) > 1 else overall_max
        overall_stdev = statistics.stdev(all_times) if len(all_times) > 1 else 0
    else:
        overall_avg = overall_min = overall_max = overall_median = overall_p95 = overall_stdev = 0

    print(f"  Total Requests:  {total_requests}")
    print(f"  Success Rate:    {success_rate:.1f}%")
    print(f"  Avg Response:    {overall_avg:.2f}s")
    print(f"  Median Response: {overall_median:.2f}s")
    print(f"  P95 Response:    {overall_p95:.2f}s")
    print(f"  Min Response:    {overall_min:.2f}s")
    print(f"  Max Response:    {overall_max:.2f}s")
    print(f"  Std Deviation:   {overall_stdev:.2f}s")

    if all_tokens_per_sec:
        print(f"  Avg Tok/s:       {statistics.mean(all_tokens_per_sec):.1f} tokens/second")

    # Concurrency note
    print(f"\n{DIM}Note: All agents share a single Ollama instance. Concurrent requests{NC}")
    print(f"{DIM}are serialized at the LLM layer — true parallel inference requires{NC}")
    print(f"{DIM}separate Ollama instances or multi-GPU splitting.{NC}")
    print(f"{BLUE}--------------------------------------------------{NC}")


def main():
    print(f"{BLUE}--------------------------------------------------{NC}")
    print(f"{GREEN}   Pi Agent Cluster — Concurrent Load Test{NC}")
    print(f"{BLUE}--------------------------------------------------{NC}")

    # Detect agents
    print(f"\n{YELLOW}Detecting running agents...{NC}")
    agents = detect_agents()

    if not agents:
        print(f"{RED}No running agents detected!{NC}")
        print(f"{YELLOW}Start the cluster first: ./manage.sh or docker compose up -d{NC}")
        sys.exit(1)

    healthy = sum(1 for a in agents.values() if a["healthy"])
    print(f"  Found {len(agents)} agent(s), {healthy} healthy")

    for num in sorted(agents):
        a = agents[num]
        badge = f"{GREEN}●{NC}" if a["healthy"] else f"{RED}●{NC}"
        print(f"  {badge}  {a['name']} (Port {a['port']}) — {a['status']}")

    if healthy == 0:
        print(f"\n{RED}No healthy agents available for testing.{NC}")
        sys.exit(1)

    # Determine test parameters
    num_rounds = 2  # default
    if len(sys.argv) > 1:
        try:
            num_rounds = int(sys.argv[1])
        except ValueError:
            print(f"{RED}Invalid round count. Usage: ./test_cluster.sh [rounds]{NC}")
            sys.exit(1)

    max_workers = None  # unlimited by default
    if len(sys.argv) > 2:
        try:
            max_workers = int(sys.argv[2])
        except ValueError:
            pass

    # Run the test
    results = run_concurrent_test(agents, num_rounds=num_rounds, max_workers=max_workers)

    # Print report
    print_report(results, agents)


if __name__ == "__main__":
    main()
