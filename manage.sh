#!/bin/zsh

# Pi Cluster Management Tool
# Allows managing the number of agents and cluster state.

# Colors
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

echo "${BLUE}--------------------------------------------------${NC}"
echo "${GREEN}   Pi Agent Cluster Manager${NC}"
echo "${BLUE}--------------------------------------------------${NC}"

while true; do
    echo "\n${BOLD}Main Menu:${NC}"
    echo "1) Status (docker compose ps)"
    echo "2) Start Cluster (up -d)"
    echo "3) Stop Cluster (down)"
    echo "4) Restart Cluster"
    echo "5) Scale Cluster (Change N agents)"
    echo "6) View Logs (tail)"
    echo "q) Quit"

    print -n "${BOLD}Option > ${NC}"
    read choice

    case $choice in
        1)
            echo "${BLUE}Current Cluster Status:${NC}"
            docker compose ps
            ;;
        2)
            echo "${GREEN}Starting cluster...${NC}"
            docker compose up -d
            ;;
        3)
            echo "${YELLOW}Stopping cluster...${NC}"
            docker compose down
            ;;
        4)
            echo "${GREEN}Restarting cluster...${NC}"
            docker compose restart
            ;;
        5)
            echo "${BLUE}How many agents would you like to run?${NC}"
            print -n "Enter N (e.g., 3, 4): "
            read n_agents

            if [[ ! "$n_agents" =~ ^[0-9]+$ ]]; then
                echo "${RED}Error: Please enter a valid number.${NC}"
                continue
            fi

            echo "${YELLOW}Scaling cluster to $n_agents agents...${NC}"

            # 1. Create necessary workspace directories for the new agents
            for i in {1..$n_agents}; do
                mkdir -p "workspaces/p$i"
            done

            # 2. Update docker-compose.yml dynamically
            # Since docker-compose.yml is currently static, we need to rewrite it.
            # We'll use a template-like approach.

            cat <<EOF > docker-compose.yml
services:
$(for i in {1..$n_agents}; do
                echo "  agent$i:"
                echo "    build: ."
                echo "    container_name: pi-agent-$i"
                echo "    hostname: pi-agent-$i"
                echo "    user: \"1000:1000\""
                echo "    volumes:"
                echo "      - ./workspaces/p$i:/home/pi/.pi_workspace"
                echo "      - ./config/agent/models.json:/home/pi/.pi/agent/models.json:ro"
                echo "    environment:"
                echo "      - PI_WORKSPACE=/home/pi/.pi_workspace"
                echo "      - OLLAMA_BASE_URL=http://host.docker.internal:11434"
                echo "    ports:"
                echo "      - \"$((8000+i)):8000\""
                echo "    networks:"
                echo "      - pi-network"
                echo "    deploy:"
                echo "      resources:"
                echo "        limits:"
                echo "          memory: 8G"
                echo "    healthcheck:"
                echo "      test: [\"CMD\", \"curl\", \"-f\", \"http://localhost:8000/health\"]"
                echo "      interval: 30s"
                echo "      timeout: 10s"
                echo "      retries: 3"
                echo "    restart: unless-stopped"
                echo ""
done)
networks:
  pi-network:
    driver: bridge
EOF

            docker compose up -d
            echo "${GREEN}Successfully scaled to $n_agents agents.${NC}"
            ;;
        6)
            echo "${BLUE}Tailing logs (Ctrl+C to return)...${NC}"
            docker compose logs -f
            ;;
        q)
            echo "Exiting manager. Bye!"
            exit 0
            ;;
        *)
            echo "${RED}Invalid option.${NC}"
            ;;
    esac
    echo "${BLUE}--------------------------------------------------${NC}"
done
