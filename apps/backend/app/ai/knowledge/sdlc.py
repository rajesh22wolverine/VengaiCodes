# ═══════════════════════════════════════════════════════════════
#  VengaiCode — SDLC phase knowledge
#  ai/knowledge/sdlc.py — What good practice looks like in each phase
#  VengaiCode walks a project through, as data: the standard formats,
#  methods and tools of the phase, and short prompt-ready rules. Each AI
#  phase prompt can include its phase's rules (phase_rules_for_prompt);
#  the catalog is served read-only at GET /api/v1/knowledge.
# ═══════════════════════════════════════════════════════════════

from dataclasses import dataclass


@dataclass(frozen=True)
class PhaseSpec:
    key: str
    label: str
    methods: tuple[str, ...]  # standards, formats and techniques
    tools: tuple[str, ...]  # tools and frameworks
    rules: tuple[str, ...]  # prompt-ready rules


SDLC_PHASES: tuple[PhaseSpec, ...] = (
    PhaseSpec(
        key="requirements",
        label="Requirements",
        methods=(
            "User stories (As a <role>, I want <goal>, so that <benefit>)",
            "Acceptance criteria in Given/When/Then (Gherkin)",
            "INVEST criteria for stories",
            "MoSCoW prioritization",
            "Use cases",
            "ISO/IEC/IEEE 29148 requirements specification",
            "ISO/IEC 25010 quality attributes for non-functional requirements",
        ),
        tools=("Jira", "Linear", "GitHub Issues", "Cucumber"),
        rules=(
            "Every requirement is testable: it has acceptance criteria someone can check.",
            "Separate functional requirements from non-functional ones (performance, security, accessibility, privacy).",
            "Write user stories from a real user role, one goal each.",
            "State what is out of scope, not only what is in.",
        ),
    ),
    PhaseSpec(
        key="uiux",
        label="UI/UX design",
        methods=(
            "WCAG 2.2 AA accessibility",
            "Atomic design (atoms, molecules, organisms)",
            "Design tokens (color, type, spacing)",
            "Mobile-first responsive layout",
            "Material Design 3 / Apple Human Interface Guidelines / Fluent",
        ),
        tools=("Figma", "GrapesJS", "Tailwind CSS", "Storybook"),
        rules=(
            "Text contrast at least 4.5:1; touch targets at least 44x44 px; everything reachable by keyboard.",
            "Every screen designs its loading, empty and error states, not only the happy path.",
            "Use a consistent spacing and type scale from design tokens.",
        ),
    ),
    PhaseSpec(
        key="architecture",
        label="Architecture",
        methods=(
            "C4 model (context, container, component, code)",
            "UML and entity-relationship diagrams (Mermaid)",
            "Architecture Decision Records (Nygard format)",
            "Layered / MVC / hexagonal (ports & adapters) / clean architecture",
            "Microservices and event-driven architecture",
            "REST (OpenAPI 3), GraphQL, gRPC API styles",
            "The Twelve-Factor App",
            "Database normalization (3NF) and explicit constraints",
        ),
        tools=("Mermaid", "PlantUML", "OpenAPI", "Structurizr"),
        rules=(
            "Record every significant decision as an ADR: context, decision, consequences.",
            "Model data with explicit keys, types, foreign keys and constraints — not free text.",
            "Prefer the simplest architecture that meets the requirements; a modular monolith before microservices.",
            "Configuration comes from the environment; secrets never live in code.",
        ),
    ),
    PhaseSpec(
        key="implementation",
        label="Implementation",
        methods=(
            "Clean code",
            "SOLID",
            "DRY / KISS / YAGNI",
            "Secure coding (OWASP Top 10)",
            "Semantic versioning",
        ),
        tools=(
            "Git",
            "formatters and linters per language (see languages)",
            "code review",
        ),
        rules=(
            "Validate every input at the boundary; parameterize all database queries (OWASP A03).",
            "Handle and log errors; never swallow them silently.",
            "Keep functions small with one responsibility; name things for what they mean.",
        ),
    ),
    PhaseSpec(
        key="testing",
        label="Testing",
        methods=(
            "Test pyramid: many unit, fewer integration, few end-to-end tests",
            "Arrange / Act / Assert",
            "Test-driven and behaviour-driven development (TDD / BDD)",
            "Boundary-value and equivalence-class testing",
            "Code coverage as a signal, not a goal",
        ),
        tools=(
            "pytest",
            "Jest",
            "Vitest",
            "JUnit 5",
            "xUnit",
            "RSpec",
            "PHPUnit",
            "Go testing",
            "cargo test",
            "Playwright",
            "Cypress",
        ),
        rules=(
            "Each test checks one behaviour and names it.",
            "Tests are independent and repeatable: no order dependence, no shared mutable state, no real network.",
            "Cover the error paths and the edges (empty, maximum, invalid), not only the happy path.",
        ),
    ),
    PhaseSpec(
        key="deployment",
        label="Deployment",
        methods=(
            "Continuous integration / continuous delivery",
            "Infrastructure as code",
            "Blue-green and canary releases",
            "Immutable builds",
        ),
        tools=(
            "GitHub Actions",
            "Docker (OCI images)",
            "PyInstaller",
            "Tauri",
            "Capacitor",
            "Gradle",
            "Xcode",
        ),
        rules=(
            "Every build is reproducible from a pinned lockfile.",
            "Database migrations run before the new version serves traffic, and are backward compatible.",
            "Health-check endpoints and a rollback plan for every release.",
        ),
    ),
    PhaseSpec(
        key="maintenance",
        label="Maintenance",
        methods=(
            "Semantic versioning",
            "Keep a Changelog",
            "Structured logging",
            "Monitoring and alerting (SLOs)",
            "Dependency updates",
        ),
        tools=("Sentry", "Prometheus / Grafana", "Dependabot", "Renovate"),
        rules=(
            "Log with levels and context, never secrets or personal data.",
            "Update dependencies regularly and read their changelogs for breaking changes.",
            "Every bug fix comes with a test that would have caught it.",
        ),
    ),
)


def phase(key: str | None) -> PhaseSpec | None:
    return next((p for p in SDLC_PHASES if p.key == (key or "").strip().lower()), None)
