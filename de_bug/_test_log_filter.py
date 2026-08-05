from app.services.agent.mcp.local_server import LocalMCPServer

sample = "\n".join([
    "Get:1 http://deb.debian.org/debian trixie/main amd64 libsystemd-shared amd64 [2155 kB]",
    "Get:2 http://deb.debian.org/debian trixie/main amd64 libapparmor1 amd64 [43.7 kB]",
    "Package 'openjdk-17-jre' is not installed, so not removed",
    "Package 'openjdk-17-jre' is not installed, so not removed",
    "Package 'openjdk-17-jre' is not installed, so not removed",
    "[2026-08-05 03:08:43] 后台 Job 仍在运行，30s 没有新输出（已运行 55s / 超时 1800s）",
    "JAVA_STILL_INSTALLED",
    'openjdk version "17.0.20" 2026-07-21',
])
out = LocalMCPServer._filter_terminal_log_for_agent(sample)
print(out)
print("---")
print("chars:", len(out))
