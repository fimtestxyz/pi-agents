#!/usr/bin/env python3
"""
Pi Agent Interactive CLI Chat Client.
Auto-detects running agents, supports streaming, slash commands, raw mode.
"""

import http.client
import json
import os
import subprocess
import sys
import urllib.parse

# Colors
BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
NC = "\033[0m"


def detect_agents():
    """Probe Docker for running pi-agent containers and check their health."""
    agents = {}
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return agents

        # Docker compose ps --format json may output one JSON object per line
        # or a JSON array depending on version; handle both
        text = result.stdout.strip()
        if not text:
            return agents

        containers = []
        # Try parsing as a JSON array first
        try:
            containers = json.loads(text)
            if not isinstance(containers, list):
                containers = [containers]
        except json.JSONDecodeError:
            # Fall back to line-delimited JSON
            for line in text.splitlines():
                line = line.strip()
                if line:
                    try:
                        containers.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        for c in containers:
            name = c.get("Name", c.get("name", ""))
            if not name.startswith("pi-agent-"):
                continue
            state = c.get("State", c.get("state", ""))
            status = c.get("Status", c.get("status", ""))
            health = c.get("Health", c.get("health", ""))
            # Derive agent number from container name: pi-agent-1 → 1
            try:
                agent_num = int(name.split("-")[-1])
            except ValueError:
                continue
            # Port mapping: agent N → port 8000+N
            port = 8000 + agent_num
            is_healthy = state.lower() == "running" and (
                "healthy" in status.lower() or health.lower() == "healthy"
            )
            agents[agent_num] = {
                "name": name,
                "port": port,
                "state": state,
                "status": status,
                "healthy": is_healthy,
            }
    except FileNotFoundError:
        # docker not found — fall back to port scanning
        pass
    except subprocess.TimeoutExpired:
        pass

    # If docker compose didn't find anything, fall back to port scanning
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
                        "state": "running",
                        "status": "healthy",
                        "healthy": True,
                    }
                conn.close()
            except Exception:
                pass

    return agents


class ChatClient:
    def __init__(self):
        self.port = 8001
        self.agent_name = "pi-agent-1"
        self.agent_num = 1
        self.model = "gemma4-local"
        self.streaming = True
        self.raw_mode = False
        self.show_reasoning = True
        self.history = []
        self.available_agents = {}  # populated at startup

    def print_help(self):
        agent_list = ", ".join(
            str(n) for n in sorted(self.available_agents)
        ) or "none detected"
        print(f"\n{BOLD}Available Slash Commands:{NC}")
        print(f"  {BOLD}/help{NC}          - Show this help message")
        print(f"  {BOLD}/agent [N]{NC}     - Switch agent (detected: {agent_list})")
        print(f"  {BOLD}/agents{NC}        - List detected agents and their status")
        print(f"  {BOLD}/stream{NC}        - Toggle streaming on/off (currently: {'ON' if self.streaming else 'OFF'})")
        print(f"  {BOLD}/raw{NC}           - Toggle raw JSON view on/off (currently: {'ON' if self.raw_mode else 'OFF'})")
        print(f"  {BOLD}/reason{NC}        - Toggle reasoning display on/off (currently: {'ON' if self.show_reasoning else 'OFF'})")
        print(f"  {BOLD}/clear{NC}         - Clear conversation history")
        print(f"  {BOLD}/history{NC}       - Print conversation history")
        print(f"  {BOLD}/exit{NC} or {BOLD}/quit{NC} - Exit the chat application\n")

    def select_agent_prompt(self):
        print(f"{BLUE}--------------------------------------------------{NC}")
        print(f"{GREEN}   Pi Agent Cluster Interactive Chat{NC}")
        print(f"{BLUE}--------------------------------------------------{NC}")

        print(f"{YELLOW}Detecting running agents...{NC}")
        self.available_agents = detect_agents()

        if not self.available_agents:
            print(f"\n{RED}No running agents detected!${NC}")
            print(f"{YELLOW}Start the cluster first: ./manage.sh or docker compose up -d{NC}")
            sys.exit(1)

        print(f"\n{GREEN}Detected {len(self.available_agents)} agent(s):{NC}")
        for num in sorted(self.available_agents):
            a = self.available_agents[num]
            health_badge = f"{GREEN}●{NC}" if a["healthy"] else f"{RED}●{NC}"
            print(f"  {health_badge}  {BOLD}{num}{NC}) {a['name']} (Port {a['port']}) — {a['status']}")

        print(f"\nChoose an agent to connect to (1-{max(self.available_agents)}), or q to quit.")

        try:
            choice = input(f"{BOLD}Option > {NC}").strip()
            if choice in ("q", "Q", "/exit", "/quit"):
                print("Exiting...")
                sys.exit(0)

            try:
                agent_num = int(choice)
                if agent_num in self.available_agents:
                    self.setup_agent(agent_num)
                else:
                    print(f"{RED}Agent {agent_num} not found. Available: {sorted(self.available_agents)}{NC}")
                    # Default to first healthy agent
                    healthy = [n for n, a in self.available_agents.items() if a["healthy"]]
                    if healthy:
                        fallback = min(healthy)
                        print(f"{YELLOW}Defaulting to Agent {fallback}.{NC}")
                        self.setup_agent(fallback)
                    else:
                        print(f"{RED}No healthy agents available. Exiting.{NC}")
                        sys.exit(1)
            except ValueError:
                print(f"{RED}Invalid input. Exiting.{NC}")
                sys.exit(1)
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            sys.exit(0)

    def setup_agent(self, agent_num):
        self.agent_num = agent_num
        self.port = 8000 + agent_num
        self.agent_name = f"pi-agent-{agent_num}"
        print(f"\n{GREEN}Connected to {self.agent_name} on port {self.port}{NC}")
        print(f"Type {BOLD}/help{NC} for commands. Happy chatting!\n")

    def post_chat_completion(self):
        parsed_url = urllib.parse.urlparse(f"http://localhost:{self.port}")
        conn = http.client.HTTPConnection(parsed_url.hostname, parsed_url.port, timeout=120)

        should_stream = self.streaming and not self.raw_mode
        payload = {
            "model": self.model,
            "messages": self.history,
            "stream": should_stream
        }
        headers = {"Content-Type": "application/json"}
        json_payload = json.dumps(payload)

        try:
            conn.request("POST", "/v1/chat/completions", body=json_payload, headers=headers)
            response = conn.getresponse()

            if response.status != 200:
                print(f"\n{RED}Error: Server returned status {response.status}{NC}")
                print(response.read().decode())
                return None

            if should_stream:
                return self.handle_streaming_response(response)
            else:
                return self.handle_standard_response(response)

        except Exception as e:
            print(f"\n{RED}Connection failed: {e}{NC}")
            print(f"{YELLOW}Ensure the container is running and healthy: docker compose ps{NC}")
            return None
        finally:
            conn.close()

    def handle_standard_response(self, response):
        raw_body = response.read().decode()

        if self.raw_mode:
            print(f"\n{YELLOW}[Raw Response]{NC}")
            print(raw_body)
            print(f"{YELLOW}[End Raw]{NC}")

        try:
            data = json.loads(raw_body)
            if "error" in data:
                print(f"\n{RED}API Error: {data['error'].get('message', data['error'])}{NC}")
                return None

            choice = data["choices"][0]
            message = choice["message"]
            content = message.get("content", "")
            reasoning = message.get("reasoning", "")

            if reasoning and self.show_reasoning:
                print(f"\n{DIM}{BOLD}[Thinking Process]{NC}")
                print(f"{DIM}{reasoning.strip()}{NC}")
                print(f"{DIM}{BOLD}[End Thinking]{NC}\n")

            print(f"\n{BLUE}{self.agent_name} > {NC}{content.strip()}\n")
            return content
        except Exception as e:
            print(f"\n{RED}Failed to parse JSON response: {e}{NC}")
            print(f"{YELLOW}Response was: {raw_body[:500]}{NC}")
            return None

    def handle_streaming_response(self, response):
        print(f"\n{BLUE}{self.agent_name} > {NC}", end="", flush=True)
        full_content = []
        full_reasoning = []
        is_thinking = False

        buffer = ""
        try:
            while True:
                chunk = response.read(1).decode("utf-8", errors="ignore")
                if not chunk:
                    break
                buffer += chunk

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()

                    if not line:
                        continue

                    if line.startswith("data: [DONE]"):
                        break

                    if line.startswith("data: "):
                        json_str = line[6:]
                        try:
                            data = json.loads(json_str)
                            choice = data["choices"][0]

                            delta = choice.get("delta", {})
                            content_piece = delta.get("content", "")
                            reasoning_piece = delta.get("reasoning", "")

                            if reasoning_piece and self.show_reasoning:
                                if not is_thinking:
                                    print(f"\n{DIM}{BOLD}[Thinking Process]{NC}\n{DIM}", end="", flush=True)
                                    is_thinking = True
                                print(reasoning_piece, end="", flush=True)
                                full_reasoning.append(reasoning_piece)

                            if content_piece:
                                if is_thinking:
                                    print(f"{NC}\n{DIM}{BOLD}[End Thinking]{NC}\n\n{BLUE}{self.agent_name} > {NC}", end="", flush=True)
                                    is_thinking = False

                                print(content_piece, end="", flush=True)
                                full_content.append(content_piece)

                        except Exception:
                            pass

            if is_thinking:
                print(f"{NC}\n{DIM}{BOLD}[End Thinking]{NC}")

            print("\n")
            final_text = "".join(full_content)
            return final_text if final_text else None

        except KeyboardInterrupt:
            print(f"\n{YELLOW}[Stream Interrupted by user]{NC}\n")
            return None

    def handle_command(self, cmd_line):
        tokens = cmd_line.strip().split()
        if not tokens:
            return True

        cmd = tokens[0].lower()
        args = tokens[1:]

        if cmd in ("/exit", "/quit"):
            print("Exiting...")
            return False

        elif cmd == "/help":
            self.print_help()

        elif cmd == "/agents":
            print(f"\n{BOLD}Re-detecting agents...{NC}")
            self.available_agents = detect_agents()
            if not self.available_agents:
                print(f"{RED}No running agents detected.{NC}")
            else:
                for num in sorted(self.available_agents):
                    a = self.available_agents[num]
                    health_badge = f"{GREEN}●{NC}" if a["healthy"] else f"{RED}●{NC}"
                    current = f" {YELLOW}← current{NC}" if num == self.agent_num else ""
                    print(f"  {health_badge}  {BOLD}{num}{NC}) {a['name']} (Port {a['port']}) — {a['status']}{current}")
            print()

        elif cmd == "/stream":
            self.streaming = not self.streaming
            print(f"{YELLOW}Streaming is now {'ON' if self.streaming else 'OFF'}.{NC}")

        elif cmd == "/raw":
            self.raw_mode = not self.raw_mode
            print(f"{YELLOW}Raw JSON view is now {'ON' if self.raw_mode else 'OFF'}.{NC}")

        elif cmd == "/reason":
            self.show_reasoning = not self.show_reasoning
            print(f"{YELLOW}Show reasoning is now {'ON' if self.show_reasoning else 'OFF'}.{NC}")

        elif cmd == "/clear":
            self.history = []
            print(f"{YELLOW}Conversation history cleared.{NC}")

        elif cmd == "/history":
            print(f"\n{BOLD}Conversation History:{NC}")
            for msg in self.history:
                role = msg["role"]
                color = GREEN if role == "user" else BLUE
                # Truncate long messages for readability
                content = msg["content"]
                if len(content) > 200:
                    content = content[:200] + "..."
                print(f"{color}{role.capitalize()}:{NC} {content}")
            print()

        elif cmd == "/agent":
            if not args:
                print(f"{YELLOW}Currently connected to {self.agent_name} (Port {self.port}).{NC}")
                print(f"{YELLOW}Usage: /agent <N>  where N is one of: {sorted(self.available_agents)}{NC}")
            else:
                try:
                    agent_num = int(args[0])
                    if agent_num in self.available_agents:
                        self.setup_agent(agent_num)
                    else:
                        # Maybe the cluster was scaled — re-detect
                        print(f"{YELLOW}Agent {agent_num} not in cache. Re-detecting...{NC}")
                        self.available_agents = detect_agents()
                        if agent_num in self.available_agents:
                            self.setup_agent(agent_num)
                        else:
                            print(f"{RED}Agent {agent_num} not found. Available: {sorted(self.available_agents)}{NC}")
                except ValueError:
                    print(f"{RED}Invalid agent ID. Enter a number.{NC}")

        else:
            print(f"{RED}Unknown command: {cmd}. Type /help for assistance.{NC}")

        return True

    def run(self):
        self.select_agent_prompt()

        while True:
            try:
                user_input = input(f"{BOLD}{GREEN}User > {NC}").strip()
                if not user_input:
                    continue

                if user_input.startswith("/"):
                    keep_running = self.handle_command(user_input)
                    if not keep_running:
                        break
                    continue

                self.history.append({"role": "user", "content": user_input})

                response_text = self.post_chat_completion()
                if response_text:
                    self.history.append({"role": "assistant", "content": response_text})
                else:
                    self.history.pop()

            except (KeyboardInterrupt, EOFError):
                print("\nExiting...")
                break


if __name__ == "__main__":
    client = ChatClient()
    client.run()
