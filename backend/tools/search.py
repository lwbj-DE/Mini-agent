"""Mock search tool with a small built-in knowledge base.

In production this would call a real search API (Brave, Tavily, etc.).
"""

from typing import Any

from .base import BaseTool

# ---------- mock knowledge base ----------
_KNOWLEDGE: dict[str, str] = {
    # Programming
    "python": (
        "Python is a high-level, interpreted programming language known for "
        "its readability and versatility. Created by Guido van Rossum and "
        "first released in 1991. Latest stable version: 3.12. "
        "Common uses: web development (Django, FastAPI), data science "
        "(pandas, numpy), AI/ML (PyTorch, TensorFlow), automation, and DevOps."
    ),
    "rust": (
        "Rust is a systems programming language focused on safety, speed, and "
        "concurrency. Created by Graydon Hoare at Mozilla Research. First "
        "stable release: 2015. Key features: ownership system, borrow checker, "
        "zero-cost abstractions, guaranteed memory safety without garbage "
        "collection. Used in browsers (Servo, Firefox), operating systems, "
        "blockchain, and CLI tools."
    ),
    "fastapi": (
        "FastAPI is a modern, fast (high-performance) Python web framework "
        "for building APIs. Based on standard Python type hints. Key features: "
        "automatic OpenAPI docs, async support, data validation via Pydantic, "
        "dependency injection system. Created by Sebastián Ramírez."
    ),
    "ai agent": (
        "An AI agent is an autonomous system that perceives its environment, "
        "makes decisions, and takes actions to achieve goals. Key components: "
        "LLM (reasoning), tools (actions), memory (context), and planning "
        "(task decomposition). Common patterns: ReAct (Reasoning + Acting), "
        "ReWOO (Reasoning Without Observation), Plan-and-Execute."
    ),
    "react pattern": (
        "ReAct (Reasoning + Acting) is a pattern for AI agents where the "
        "model interleaves reasoning steps with tool-use actions. The agent "
        "thinks about what to do, calls a tool, observes the result, and "
        "repeats until it can provide a final answer. This allows the agent "
        "to gather information and perform actions iteratively."
    ),
    # General knowledge
    "earth": (
        "Earth is the third planet from the Sun and the only known "
        "astronomical object to harbor life. Radius: ~6,371 km. Surface area: "
        "~510 million km² (71% water). One moon. Orbital period: 365.25 days."
    ),
    "mimo model": (
        "MiMo (Mini-Mo) is a series of large language models developed by "
        "Xiaomi. MiMo-V2.5-Pro is a flagship reasoning model with strong "
        "performance on math, coding, and general reasoning tasks. It supports "
        "function calling, reasoning/thinking tokens, and long context windows."
    ),
    "llm": (
        "Large Language Models (LLMs) are neural networks trained on vast "
        "text corpora to predict the next token. They exhibit emergent "
        "abilities like reasoning, coding, translation, and creative writing. "
        "Popular models include GPT-4, Claude, Gemini, and open-source models "
        "like Llama, Qwen, and DeepSeek. Key techniques: transformer "
        "architecture, RLHF, and mixture-of-experts."
    ),
    "tokyo": (
        "Tokyo is the capital of Japan and one of the most populous "
        "metropolitan areas in the world (~37 million people). Known for "
        "its blend of ultramodern and traditional culture. Key landmarks: "
        "Shibuya Crossing, Tokyo Tower, Senso-ji Temple, Meiji Shrine. "
        "Hosted the 2020 Summer Olympics (held in 2021)."
    ),
    "climate change": (
        "Climate change refers to long-term shifts in temperatures and "
        "weather patterns, primarily driven by human activities — especially "
        "burning fossil fuels since the Industrial Revolution. Key effects: "
        "rising global temperatures, sea level rise, extreme weather events, "
        "ecosystem disruption. The Paris Agreement (2015) aims to limit "
        "warming to well below 2°C above pre-industrial levels."
    ),
    # Programming languages
    "c++": (
        "C++ is a general-purpose programming language created by Bjarne "
        "Stroustrup in 1985 as an extension of C. It supports procedural, "
        "object-oriented, and generic programming. Key features: classes, "
        "inheritance, polymorphism, templates, RAII, move semantics, "
        "STL (Standard Template Library). Latest standard: C++23. "
        "Setup: install GCC/MinGW (Windows) or Clang/GCC (macOS/Linux). "
        "Hello World: #include <iostream> → int main() { std::cout << "
        "\"Hello World\" << std::endl; return 0; }"
    ),
    "c++ 环境搭建": (
        "C++ 环境搭建步骤：1) Windows: 安装 MinGW-w64 或 Visual Studio "
        "(含 MSVC 编译器)，配置 PATH 环境变量；2) macOS: xcode-select "
        "--install 安装 Clang；3) Linux: sudo apt install build-essential "
        "或 sudo yum install gcc-c++。验证安装: g++ --version 或 clang++ "
        "--version。推荐 IDE: VS Code + C/C++ 插件, CLion, Visual Studio。"
    ),
    "c++ stl": (
        "C++ STL (Standard Template Library) 核心组件：容器 (vector, list, "
        "map, set, unordered_map)，算法 (sort, find, binary_search, "
        "for_each)，迭代器，函数对象。vector 是动态数组，map 是红黑树 "
        "键值对，unordered_map 是哈希表。使用 #include <vector> 等头文件。"
    ),
    "c++ 面向对象": (
        "C++ 面向对象编程核心概念：类 (class) 和对象、封装 (private/public)、"
        "继承 (单继承/多继承)、多态 (虚函数 virtual、纯虚函数 =0、抽象类)。"
        "构造函数和析构函数管理资源生命周期，RAII 惯用法用对象生命周期管理"
        "资源（如智能指针 unique_ptr/shared_ptr）。"
    ),
    "java": (
        "Java is a class-based, object-oriented programming language created "
        "by James Gosling at Sun Microsystems (1995). 'Write Once, Run "
        "Anywhere' via JVM. Key features: garbage collection, strong typing, "
        "multithreading. Common uses: enterprise apps (Spring Boot), Android "
        "development, big data (Hadoop). Latest LTS: Java 21."
    ),
    "javascript": (
        "JavaScript (JS) is a dynamic, interpreted programming language, "
        "primarily used for web development. Runs in browsers and on servers "
        "(Node.js). ES6+ features: arrow functions, promises, async/await, "
        "destructuring, modules. Popular frameworks: React, Vue, Angular. "
        "TypeScript adds static typing to JavaScript."
    ),
    "go": (
        "Go (Golang) is a statically typed, compiled language designed by "
        "Google (2009). Key features: goroutines (lightweight concurrency), "
        "channels, fast compilation, garbage collection, simple syntax. "
        "Popular for cloud services, CLI tools, DevOps (Docker, Kubernetes "
        "are written in Go)."
    ),
    # Tools & infrastructure
    "git": (
        "Git is a distributed version control system created by Linus "
        "Torvalds (2005). Key concepts: repository, commit, branch, merge, "
        "remote (origin), pull/push. Common commands: git init, git add, "
        "git commit -m, git push, git pull, git branch, git merge, git clone."
    ),
    "docker": (
        "Docker is a platform for developing, shipping, and running "
        "applications in containers. Container vs VM: containers share the "
        "host OS kernel, making them lightweight. Key concepts: Dockerfile, "
        "image, container, docker-compose, registry (Docker Hub). Common "
        "commands: docker build, docker run, docker ps, docker compose up."
    ),
    "linux": (
        "Linux is an open-source Unix-like operating system kernel created "
        "by Linus Torvalds (1991). Common distributions: Ubuntu, Debian, "
        "CentOS/RHEL, Arch. Key concepts: shell (bash), file system hierarchy, "
        "package managers (apt, yum, pacman), permissions (chmod), processes, "
        "systemd. Essential commands: ls, cd, grep, find, chmod, sudo, systemctl."
    ),
    "sql": (
        "SQL (Structured Query Language) is the standard language for "
        "relational databases. Key operations: SELECT, INSERT, UPDATE, DELETE. "
        "Clauses: WHERE, JOIN (INNER/LEFT/RIGHT), GROUP BY, HAVING, ORDER BY. "
        "Popular RDBMS: PostgreSQL, MySQL, SQLite, SQL Server. ACID: Atomicity, "
        "Consistency, Isolation, Durability."
    ),
    "http": (
        "HTTP (Hypertext Transfer Protocol) is the foundation of data "
        "communication on the Web. Methods: GET (read), POST (create), PUT "
        "(update), DELETE (delete), PATCH (partial update). Status codes: "
        "2xx success, 3xx redirect, 4xx client error (404 Not Found), 5xx "
        "server error. REST (Representational State Transfer) is an "
        "architectural style using HTTP methods on resources identified by URLs."
    ),
    # AI/ML
    "neural network": (
        "A neural network is a computational model inspired by biological "
        "neurons. Layers: input, hidden, output. Each neuron applies weights "
        "+ bias + activation function (ReLU, sigmoid, tanh). Training via "
        "backpropagation + gradient descent. Deep learning uses many hidden "
        "layers. Popular frameworks: PyTorch, TensorFlow, JAX."
    ),
    "transformer": (
        "The Transformer architecture (2017, 'Attention Is All You Need') "
        "revolutionized NLP and AI. Key components: self-attention mechanism, "
        "multi-head attention, positional encoding, feed-forward networks. "
        "Forms the basis of GPT, BERT, Claude, and most modern LLMs. "
        "Enables parallel processing of sequences unlike RNNs/LSTMs."
    ),
    "pytorch": (
        "PyTorch is an open-source machine learning framework by Meta AI. "
        "Key features: dynamic computation graphs (eager execution), "
        "autograd (automatic differentiation), torch.nn module for building "
        "neural networks. Common workflow: define model → define loss & "
        "optimizer → training loop → evaluation. torch.Tensor is the core "
        "data structure."
    ),
    # General dev knowledge
    "rest api": (
        "REST (Representational State Transfer) API design principles: "
        "1) Stateless — each request contains all needed info, 2) Resource-based "
        "URLs (/users/123), 3) HTTP methods (GET/POST/PUT/DELETE), 4) JSON "
        "as standard format, 5) Proper status codes. Best practices: "
        "versioning (/v1/), pagination, filtering, authentication (JWT/OAuth)."
    ),
    "json": (
        "JSON (JavaScript Object Notation) is a lightweight data interchange "
        "format. Types: string, number, boolean, null, array, object. Human-"
        "readable and language-independent. Used universally for API responses, "
        "config files, data storage. Related: JSON Schema for validation, "
        "JSON Lines (NDJSON) for streaming."
    ),
    "regex": (
        "Regular expressions (regex) are patterns for matching text. Common "
        "syntax: . (any char), * (0+), + (1+), ? (optional), ^ (start), $ "
        "(end), [abc] (character class), \\d (digit), \\w (word), \\s "
        "(whitespace), (a|b) (alternation). Used for validation, search-"
        "replace, parsing. Supported in most languages (Python re, JS RegExp)."
    ),
    # Web
    "react": (
        "React is a JavaScript library for building user interfaces, created "
        "by Meta (2013). Key concepts: components (function components + "
        "hooks), JSX, virtual DOM, state (useState), side effects (useEffect), "
        "context API. Ecosystem: Next.js (SSR/SSG), React Router, Redux/Zustand "
        "(state management)."
    ),
    "vue": (
        "Vue.js is a progressive JavaScript framework for building UIs, "
        "created by Evan You (2014). Key features: reactive data binding, "
        "template syntax, components, Vue Router, Pinia (state management). "
        "Composition API (Vue 3): ref, reactive, computed, watch, onMounted. "
        "Gentler learning curve compared to React/Angular."
    ),
}


class SearchTool(BaseTool):
    """Mock search engine tool.

    Searches a small built-in knowledge base for relevant information.
    Designed to be easily swappable with a real search API.
    """

    @property
    def name(self) -> str:
        return "search"

    @property
    def description(self) -> str:
        return (
            "Search for information on a given topic. "
            "Returns relevant knowledge if the topic is found. "
            "Use this when you need to look up facts, concepts, or data "
            "that you don't already know or need to verify."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "The search query — a few keywords or a short "
                        "question, e.g. 'Python programming language', "
                        "'climate change effects'."
                    ),
                }
            },
            "required": ["query"],
        }

    def execute(self, query: str = "", **kwargs: Any) -> str:
        """Search the knowledge base for *query*."""
        if not query:
            return "Error: no search query provided"

        q_lower = query.lower().strip()

        # Exact key match
        if q_lower in _KNOWLEDGE:
            return _KNOWLEDGE[q_lower]

        # Substring match across keys and content
        matches: list[tuple[str, str]] = []
        for key, content in _KNOWLEDGE.items():
            # Score: title match is best
            score = 0
            if key in q_lower or q_lower in key:
                score = 10
            elif any(word in key for word in q_lower.split()):
                score = 5
            elif q_lower in content.lower():
                score = 3
            if score > 0:
                matches.append((key, content))

        if not matches:
            return (
                f"No information found for '{query}'. "
                f"The knowledge base covers: {', '.join(sorted(_KNOWLEDGE.keys()))}. "
                f"Try a different query or tell the user what you know."
            )

        # Sort by score and return top results
        matches.sort(key=lambda x: len(x[1]), reverse=True)
        results: list[str] = []
        for key, content in matches[:3]:
            results.append(f"**{key.title()}**: {content}")
        return "\n\n".join(results)
