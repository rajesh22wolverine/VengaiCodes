# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Framework knowledge
#  ai/knowledge/frameworks.py — Every framework in the stack matrix
#  (app/ai/stack_matrix.py), as data: how the generated code turns a
#  table/field name into an identifier, which names collide with the
#  framework itself, its ORM and migration tool, project layout,
#  commands, and prompt-ready rules.
#
#  The collision rules are the ones that actually break builds or silently
#  misbehave — each entry says why, and that sentence is what the
#  Architecture editor shows the user:
#    Rails     a column named "type" switches on single-table inheritance
#    Flask     a "query" column shadows Flask-SQLAlchemy's Model.query
#    Django    "pk"/"objects" collide with the model API
#    C#        a property can't share its class's name (CS0542)
#    Java/C#/Rust  a model named String/Task/Box shadows a standard type
# ═══════════════════════════════════════════════════════════════

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FrameworkSpec:
    key: str
    label: str
    category: str  # "backend" | "web" | "mobile" | "game"
    languages: tuple[str, ...]
    rules: tuple[str, ...]
    # How a table's field slug becomes an identifier in generated code:
    # "snake" (as-is), "camel", "pascal", or "key" (a string key/property
    # name, where the language's keywords are legal).
    field_case: str = "key"
    reserved_fields: dict[str, str] = field(default_factory=dict)  # slug -> why
    reserved_types: frozenset[str] = frozenset()  # model class names that clash
    member_named_like_type_forbidden: bool = False
    orm: str = ""
    migrations: str = ""
    layout: dict[str, str] = field(default_factory=dict)
    commands: dict[str, str] = field(default_factory=dict)
    default_port: int | None = None
    docs: str = ""


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


FRAMEWORKS: dict[str, FrameworkSpec] = {}


def _add(spec: FrameworkSpec) -> None:
    FRAMEWORKS[spec.key] = spec


# ═══════════════════════════════════════════════
#  Backends
# ═══════════════════════════════════════════════
_add(
    FrameworkSpec(
        key="fastapi",
        label="FastAPI",
        category="backend",
        languages=("python",),
        field_case="snake",
        orm="SQLAlchemy 2 (async)",
        migrations="Alembic",
        layout={
            "models": "backend/models/<table>.py",
            "routes": "backend/routes/api.py",
            "entry": "backend/main.py",
        },
        commands={
            "install": "pip install -r requirements.txt",
            "run": "uvicorn main:app --reload",
            "test": "pytest",
        },
        default_port=8000,
        docs="https://fastapi.tiangolo.com",
        rules=(
            "Request/response bodies are Pydantic v2 models; use model_dump(), not the deprecated .dict().",
            "Use async def endpoints with an AsyncSession from Depends(get_db); await every database call.",
            "Raise HTTPException with a readable detail; 422 is FastAPI's own validation error.",
            "Mount routers with a prefix (APIRouter(prefix='/api')) and give endpoints explicit status codes.",
            "Commit, then refresh ORM objects before returning them (server defaults, onupdate columns).",
        ),
    )
)
_add(
    FrameworkSpec(
        key="flask",
        label="Flask",
        category="backend",
        languages=("python",),
        field_case="snake",
        reserved_fields={
            "query": "Flask-SQLAlchemy's Model.query, which a column with that name would replace",
            "query_class": "a Flask-SQLAlchemy model setting",
        },
        orm="Flask-SQLAlchemy",
        migrations="Flask-Migrate (Alembic)",
        layout={
            "factory": "backend/app/__init__.py (create_app)",
            "models": "backend/app/models/<table>.py",
            "routes": "backend/app/routes/api.py (Blueprint, under /api)",
        },
        commands={
            "install": "pip install -r requirements.txt",
            "run": "flask --app app run",
            "test": "pytest",
        },
        default_port=5000,
        docs="https://flask.palletsprojects.com",
        rules=(
            "Use the application-factory pattern (create_app) and Blueprints for routes.",
            "Return JSON with jsonify() and explicit status codes.",
            "Access the database through db.session inside the app context; commit or roll back per request.",
            "Never run with debug=True in production.",
        ),
    )
)
_add(
    FrameworkSpec(
        key="django",
        label="Django",
        category="backend",
        languages=("python",),
        field_case="snake",
        reserved_fields={
            "pk": "Django's alias for every model's primary key",
            "objects": "the name of every Django model's default manager",
            "save": "a Django Model method",
            "delete": "a Django Model method",
            "clean": "a Django Model validation method",
            "full_clean": "a Django Model validation method",
            "refresh_from_db": "a Django Model method",
            "check": "a Django Model system-check method",
            "models": "the generated model files' name for django.db.models (a field would replace it for every later field)",
            "serializers": "the generated serializers' name for rest_framework.serializers",
        },
        orm="Django ORM",
        migrations="Django migrations (makemigrations / migrate)",
        layout={
            "settings": "backend/config/settings.py",
            "models": "backend/api/models/<table>.py",
            "views": "backend/api/views.py",
            "urls": "backend/api/urls.py (mounted under /api/)",
            "migrations": "backend/api/migrations/",
        },
        commands={
            "install": "pip install -r requirements.txt",
            "run": "python manage.py runserver",
            "migrate": "python manage.py migrate",
            "test": "pytest",
        },
        default_port=8000,
        docs="https://docs.djangoproject.com",
        rules=(
            "Models live in an installed app; every schema change ships as a migration (makemigrations).",
            "Use Django REST Framework serializers/viewsets for JSON APIs, or JsonResponse for plain views.",
            "Field names can't contain double underscores (they mean lookups).",
            "Put secrets in environment variables, never in settings.py.",
        ),
    )
)
_add(
    FrameworkSpec(
        key="express",
        label="Express",
        category="backend",
        languages=("javascript", "typescript"),
        field_case="key",
        orm="Mongoose (MongoDB)",
        migrations="migrate-mongo",
        layout={
            "entry": "backend/server.js",
            "models": "backend/models/<table>.js",
            "routes": "backend/routes/api.js",
        },
        commands={
            "install": "npm install",
            "run": "node server.js",
            "test": "npm test",
        },
        default_port=5000,
        docs="https://expressjs.com",
        rules=(
            "Wrap async handlers so rejected promises reach an error-handling middleware (4 arguments).",
            "Parse JSON with express.json() and validate input before touching the database.",
            "Send errors as JSON with an explicit status; never leak stack traces to clients.",
            "Read configuration from process.env (dotenv in development).",
        ),
    )
)
_add(
    FrameworkSpec(
        key="nestjs",
        label="NestJS",
        category="backend",
        languages=("typescript", "javascript"),
        field_case="key",
        reserved_types=_words(
            "Module Controller Injectable Repository Entity Column Get Post Put Delete Body Param Query"
        ),
        orm="TypeORM / Prisma",
        migrations="TypeORM migrations",
        layout={
            "entry": "backend/src/main.ts",
            "module": "backend/src/app.module.ts",
            "feature": "backend/src/<feature>/<feature>.{module,controller,service,entity}.ts",
        },
        commands={
            "install": "npm install",
            "run": "npm run start:dev",
            "build": "npm run build",
            "test": "npm test",
        },
        default_port=3000,
        docs="https://docs.nestjs.com",
        rules=(
            "One module per feature with its controller, service and entity; register it in AppModule.",
            "Controllers stay thin — logic lives in @Injectable services, injected through constructors.",
            "Validate DTOs with class-validator and the global ValidationPipe.",
            "Throw Nest HTTP exceptions (NotFoundException, ConflictException…) for error responses.",
        ),
    )
)
_add(
    FrameworkSpec(
        key="spring_boot",
        label="Spring Boot",
        category="backend",
        languages=("java", "kotlin"),
        field_case="camel",
        reserved_types=_words(
            "String Object Integer Long Short Byte Double Float Boolean Character Number Class System Thread "
            "Exception Record Override List Map Set Optional Entity Table Column Id Service Repository Component"
        ),
        orm="Spring Data JPA (Hibernate)",
        migrations="Flyway",
        layout={
            "entry": "backend/src/main/java/<pkg>/Application.java",
            "entities": "backend/src/main/java/<pkg>/model/<Entity>.java",
            "repositories": "backend/src/main/java/<pkg>/repository/<Entity>Repository.java",
            "controllers": "backend/src/main/java/<pkg>/controller/<Entity>Controller.java",
            "migrations": "backend/src/main/resources/db/migration/V<n>__<name>.sql",
        },
        commands={
            "run": "./mvnw spring-boot:run",
            "build": "./mvnw package",
            "test": "./mvnw test",
        },
        default_port=8080,
        docs="https://spring.io/projects/spring-boot",
        rules=(
            "Use constructor injection (final fields), never field @Autowired.",
            "Entities use jakarta.persistence annotations (Spring Boot 3), not javax.",
            "Controllers return ResponseEntity or DTOs — not entities with lazy relations.",
            "Schema changes go in Flyway migrations; set spring.jpa.hibernate.ddl-auto=validate.",
            "Handle errors in a @RestControllerAdvice.",
        ),
    )
)
_add(
    FrameworkSpec(
        key="rails",
        label="Ruby on Rails",
        category="backend",
        languages=("ruby",),
        field_case="snake",
        reserved_fields={
            "type": "the column Rails uses for single-table inheritance (a plain 'type' column breaks loading records)",
            "class": "Ruby's Object#class, which Active Record refuses to redefine",
            "hash": "Ruby's Object#hash, which Active Record refuses to redefine",
            "object_id": "Ruby's Object#object_id",
            "send": "Ruby's Object#send",
            "method": "Ruby's Object#method",
            "methods": "Ruby's Object#methods",
            "attributes": "an Active Record method",
            "errors": "an Active Record validation method",
            "save": "an Active Record method",
            "destroy": "an Active Record method",
            "delete": "an Active Record method",
            "update": "an Active Record method",
            "reload": "an Active Record method",
            "valid": "an Active Record validation method",
            "freeze": "Ruby's Object#freeze",
            "frozen": "Ruby's Object#frozen?",
            "display": "Ruby's Object#display",
            "lock_version": "the column Rails uses for optimistic locking",
            "transaction": "an Active Record method",
            "connection": "an Active Record method",
        },
        reserved_types=_words(
            "Object String Array Hash Integer Float Symbol Kernel Class Module Comparable Enumerable Time Date Application Record"
        ),
        orm="Active Record",
        migrations="Active Record migrations",
        layout={
            "models": "backend/app/models/<table>.rb",
            "controllers": "backend/app/controllers/<tables>_controller.rb",
            "routes": "backend/config/routes.rb",
            "migrations": "backend/db/migrate/<timestamp>_<name>.rb",
        },
        commands={
            "install": "bundle install",
            "run": "bin/rails server",
            "migrate": "bin/rails db:migrate",
            "test": "bundle exec rspec",
        },
        default_port=3000,
        docs="https://guides.rubyonrails.org",
        rules=(
            "Follow conventions: singular model, plural table, <plural>_controller.rb.",
            "Use strong parameters (params.require(...).permit(...)) for create/update.",
            "Validations belong in the model; database constraints in migrations too.",
            "Render JSON with explicit status (render json: ..., status: :created).",
        ),
    )
)
_add(
    FrameworkSpec(
        key="laravel",
        label="Laravel",
        category="backend",
        languages=("php",),
        field_case="key",
        reserved_fields={
            "attributes": "an Eloquent model property",
            "original": "an Eloquent model property",
            "changes": "an Eloquent model property",
            "casts": "an Eloquent model setting",
            "fillable": "an Eloquent model setting",
            "guarded": "an Eloquent model setting",
            "hidden": "an Eloquent model setting",
            "visible": "an Eloquent model setting",
            "appends": "an Eloquent model setting",
            "table": "an Eloquent model setting",
            "connection": "an Eloquent model setting",
            "timestamps": "an Eloquent model setting",
            "incrementing": "an Eloquent model setting",
            "exists": "an Eloquent model property",
            "relations": "an Eloquent model property",
            "touches": "an Eloquent model setting",
        },
        reserved_types=_words(
            "int float bool string true false null void iterable object mixed never enum resource numeric Model Request Response Route Schema"
        ),
        orm="Eloquent",
        migrations="Laravel migrations",
        layout={
            "models": "backend/app/Models/<Model>.php",
            "controllers": "backend/app/Http/Controllers/<Model>Controller.php",
            "routes": "backend/routes/api.php",
            "migrations": "backend/database/migrations/<date>_<name>.php",
        },
        commands={
            "install": "composer install",
            "run": "php artisan serve",
            "migrate": "php artisan migrate",
            "test": "php artisan test",
        },
        default_port=8000,
        docs="https://laravel.com/docs",
        rules=(
            "Mass assignment is guarded — declare $fillable on every model.",
            "Validate requests with $request->validate([...]) or Form Request classes.",
            "Return API data with response()->json() or API Resources and proper status codes.",
            "Schema changes go in migrations; never edit a migration that already ran.",
        ),
    )
)
_add(
    FrameworkSpec(
        key="aspnet_core",
        label="ASP.NET Core",
        category="backend",
        languages=("csharp",),
        field_case="pascal",
        member_named_like_type_forbidden=True,
        reserved_types=_words(
            "String Object Task Action Func Thread Console Math File Path Type Exception Guid DateTime TimeSpan "
            "Program Controller Enum Attribute Delegate Array Random Environment"
        ),
        orm="Entity Framework Core",
        migrations="EF Core migrations",
        layout={
            "entry": "backend/Program.cs",
            "models": "backend/Models/<Model>.cs",
            "controllers": "backend/Controllers/<Model>Controller.cs",
            "context": "backend/Data/AppDbContext.cs",
        },
        commands={
            "install": "dotnet restore",
            "run": "dotnet run",
            "migrate": "dotnet ef database update",
            "test": "dotnet test",
        },
        default_port=5000,
        docs="https://learn.microsoft.com/aspnet/core",
        rules=(
            "Minimal hosting model: configure services and the pipeline in Program.cs.",
            "[ApiController] controllers return ActionResult<T>; model validation returns 400 automatically.",
            "Inject DbContext through the constructor; use async EF Core methods (ToListAsync, SaveChangesAsync).",
            "A property can't have the same name as its class (compiler error CS0542).",
        ),
    )
)
for _key, _label in (("actix", "Actix Web"), ("axum", "Axum")):
    _add(
        FrameworkSpec(
            key=_key,
            label=_label,
            category="backend",
            languages=("rust",),
            field_case="snake",
            reserved_types=_words("String Vec Option Result Box Some None Ok Err Self"),
            orm="sqlx (SQLite)",
            migrations="sqlx migrations",
            layout={
                "entry": "backend/src/main.rs",
                "models": "backend/src/models.rs",
                "handlers": "backend/src/handlers.rs",
                "manifest": "backend/Cargo.toml",
            },
            commands={
                "run": "cargo run",
                "build": "cargo build --release",
                "test": "cargo test",
            },
            default_port=8080,
            docs="https://actix.rs" if _key == "actix" else "https://docs.rs/axum",
            rules=(
                "Share the database pool through application state (web::Data / State).",
                "Map errors to HTTP responses with a custom error type implementing the framework's response trait.",
                "Derive Serialize/Deserialize with serde; sqlx::FromRow for query results.",
                "Never block the async runtime — use async database calls only.",
            ),
        )
    )
_add(
    FrameworkSpec(
        key="gin",
        label="Gin",
        category="backend",
        languages=("go",),
        field_case="pascal",
        orm="GORM",
        migrations="golang-migrate / GORM AutoMigrate",
        layout={
            "entry": "backend/main.go",
            "models": "backend/models/<table>.go",
            "handlers": "backend/handlers/<table>.go",
            "manifest": "backend/go.mod",
        },
        commands={
            "install": "go mod tidy",
            "run": "go run .",
            "build": "go build",
            "test": "go test ./...",
        },
        default_port=8080,
        docs="https://gin-gonic.com/docs",
        rules=(
            "Bind JSON with c.ShouldBindJSON and return 400 on binding errors.",
            'Exported struct fields are PascalCase with `json:"snake_case"` tags.',
            'Check every error; respond with c.JSON(status, gin.H{"error": ...}).',
            "Run gofmt; unused imports and variables don't compile.",
        ),
    )
)

# ═══════════════════════════════════════════════
#  Frontends, mobile and game engines
# ═══════════════════════════════════════════════
_add(
    FrameworkSpec(
        key="react",
        label="React",
        category="web",
        languages=("javascript", "typescript"),
        layout={
            "entry": "frontend/src/main.jsx",
            "app": "frontend/src/App.jsx",
            "screens": "frontend/src/screens/<Name>Screen.jsx",
        },
        commands={
            "install": "npm install",
            "run": "npm run dev",
            "build": "npm run build",
            "test": "npx vitest run",
        },
        default_port=5173,
        docs="https://react.dev",
        rules=(
            "Function components and hooks only; hooks are called unconditionally at the top level.",
            "Every list item has a stable key (never the array index when items can reorder).",
            "Effects declare their dependencies and clean up subscriptions/timers.",
            "Controlled inputs: value + onChange; show loading and error states for every request.",
        ),
    )
)
_add(
    FrameworkSpec(
        key="vue",
        label="Vue",
        category="web",
        languages=("javascript", "typescript"),
        layout={
            "entry": "frontend/src/main.js",
            "app": "frontend/src/App.vue",
            "screens": "frontend/src/screens/<Name>Screen.vue",
        },
        commands={
            "install": "npm install",
            "run": "npm run dev",
            "build": "npm run build",
            "test": "npx vitest run",
        },
        default_port=5173,
        docs="https://vuejs.org",
        rules=(
            "Single-file components with <script setup> and the Composition API.",
            "State with ref()/reactive(); derived values with computed().",
            "v-for always has a :key; never combine v-if and v-for on one element.",
            "Props are read-only — emit events to change parent state.",
        ),
    )
)
_add(
    FrameworkSpec(
        key="angular",
        label="Angular",
        category="web",
        languages=("typescript",),
        layout={
            "entry": "frontend/src/main.ts",
            "app": "frontend/src/app/app.component.ts",
            "features": "frontend/src/app/<feature>/<feature>.component.ts",
        },
        commands={
            "install": "npm install",
            "run": "npx ng serve",
            "build": "npx ng build",
            "test": "npx ng test",
        },
        default_port=4200,
        docs="https://angular.dev",
        rules=(
            "Standalone components with explicit imports; services are @Injectable({providedIn: 'root'}).",
            "Use HttpClient for requests and unsubscribe (or use the async pipe / takeUntilDestroyed).",
            "Signals for local state; OnPush change detection where possible.",
            "Strict TypeScript templates: every binding is type-checked.",
        ),
    )
)
_add(
    FrameworkSpec(
        key="svelte",
        label="Svelte",
        category="web",
        languages=("javascript", "typescript"),
        layout={
            "entry": "frontend/src/main.js",
            "app": "frontend/src/App.svelte",
            "screens": "frontend/src/screens/<Name>Screen.svelte",
        },
        commands={
            "install": "npm install",
            "run": "npm run dev",
            "build": "npm run build",
            "test": "npx vitest run",
        },
        default_port=5173,
        docs="https://svelte.dev",
        rules=(
            "Svelte 5 runes: $state for state, $derived for computed values, $effect for side effects.",
            "{#each} blocks use a keyed expression: {#each items as item (item.id)}.",
            "Handle events with onclick={...} attributes (Svelte 5), not on:click.",
        ),
    )
)
_add(
    FrameworkSpec(
        key="html_css_js",
        label="Plain HTML/CSS/JS",
        category="web",
        languages=("javascript",),
        layout={
            "entry": "frontend/index.html",
            "script": "frontend/app.js",
            "styles": "frontend/styles.css",
        },
        commands={"run": "open index.html (or any static server)"},
        docs="https://developer.mozilla.org",
        rules=(
            'No build step: ES modules loaded with <script type="module">.',
            "Build DOM with createElement/textContent — never innerHTML with user data (XSS).",
            "Use fetch with async/await and show errors to the user.",
        ),
    )
)
_add(
    FrameworkSpec(
        key="flutter",
        label="Flutter",
        category="mobile",
        languages=("dart",),
        layout={
            "entry": "lib/main.dart",
            "screens": "lib/screens/<name>_screen.dart",
            "manifest": "pubspec.yaml",
        },
        commands={
            "install": "flutter pub get",
            "run": "flutter run",
            "build": "flutter build apk",
            "test": "flutter test",
        },
        docs="https://docs.flutter.dev",
        rules=(
            "Compose UIs from small widgets; prefer StatelessWidget with const constructors.",
            "Keep state in a StatefulWidget or a state-management package — never in globals.",
            "Use the http/dio package with async/await and show loading/error states.",
        ),
    )
)
_add(
    FrameworkSpec(
        key="swiftui",
        label="SwiftUI",
        category="mobile",
        languages=("swift",),
        layout={"entry": "<App>App.swift", "views": "Views/<Name>View.swift"},
        commands={"build": "xcodebuild (macOS only)"},
        docs="https://developer.apple.com/documentation/swiftui",
        rules=(
            "Views are structs; state with @State, shared models with @Observable (iOS 17+) or ObservableObject.",
            "Network calls in async functions started from .task { }.",
            "Keep body small — extract subviews.",
        ),
    )
)
_add(
    FrameworkSpec(
        key="jetpack_compose",
        label="Jetpack Compose",
        category="mobile",
        languages=("kotlin",),
        layout={
            "entry": "app/src/main/java/<pkg>/MainActivity.kt",
            "screens": "app/src/main/java/<pkg>/ui/<Name>Screen.kt",
        },
        commands={"build": "./gradlew assembleDebug", "test": "./gradlew test"},
        docs="https://developer.android.com/compose",
        rules=(
            "@Composable functions are side-effect free; use LaunchedEffect for coroutines.",
            "Hoist state: screens take state + callbacks; ViewModels own it.",
            "Use Material 3 components and remember/rememberSaveable for local state.",
        ),
    )
)
_add(
    FrameworkSpec(
        key="godot",
        label="Godot Engine",
        category="game",
        languages=("gdscript",),
        layout={
            "project": "project.godot",
            "scenes": "scenes/<name>.tscn",
            "scripts": "scripts/<name>.gd",
        },
        commands={
            "run": "godot --path .",
            "export": "godot --headless --export-release",
        },
        docs="https://docs.godotengine.org",
        rules=(
            "One script per node type; attach to scenes, communicate with signals.",
            "Physics in _physics_process(delta), rendering updates in _process(delta).",
            "Use @export for inspector-tunable values and typed GDScript throughout.",
        ),
    )
)
_add(
    FrameworkSpec(
        key="o3de",
        label="Open 3D Engine (O3DE)",
        category="game",
        languages=("cpp", "lua"),
        layout={
            "project": "project.json",
            "gems": "Gem/Code/Source/",
            "scripts": "Scripts/<name>.lua",
        },
        commands={"build": "cmake --build build/windows --config profile"},
        docs="https://docs.o3de.org",
        rules=(
            "Gameplay components derive from AZ::Component and reflect with SerializeContext.",
            "Lua scripts return a table with OnActivate/OnDeactivate and disconnect handlers on deactivate.",
            "Use AZStd containers, not std, inside engine code.",
        ),
    )
)


def framework(key: str | None) -> FrameworkSpec | None:
    return FRAMEWORKS.get((key or "").strip().lower())
