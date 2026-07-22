from app.ai.codegen.backend import actix, aspnet_core, axum, django, express, fastapi, flask, gin, laravel, nestjs, rails, spring_boot
from app.ai.codegen.types import BackendAdapter

BACKEND_ADAPTERS: dict[str, BackendAdapter] = {
    fastapi.ADAPTER.key: fastapi.ADAPTER,
    express.ADAPTER.key: express.ADAPTER,
    flask.ADAPTER.key: flask.ADAPTER,
    django.ADAPTER.key: django.ADAPTER,
    nestjs.ADAPTER.key: nestjs.ADAPTER,
    spring_boot.ADAPTER.key: spring_boot.ADAPTER,
    aspnet_core.ADAPTER.key: aspnet_core.ADAPTER,
    rails.ADAPTER.key: rails.ADAPTER,
    laravel.ADAPTER.key: laravel.ADAPTER,
    actix.ADAPTER.key: actix.ADAPTER,
    axum.ADAPTER.key: axum.ADAPTER,
    gin.ADAPTER.key: gin.ADAPTER,
}
