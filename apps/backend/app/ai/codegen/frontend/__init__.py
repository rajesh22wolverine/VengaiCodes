from app.ai.codegen.frontend import angular, flutter, html_css_js, jetpack_compose, react, svelte, swiftui, vue
from app.ai.codegen.types import FrontendAdapter

FRONTEND_ADAPTERS: dict[str, FrontendAdapter] = {
    react.ADAPTER.key: react.ADAPTER,
    vue.ADAPTER.key: vue.ADAPTER,
    svelte.ADAPTER.key: svelte.ADAPTER,
    angular.ADAPTER.key: angular.ADAPTER,
    html_css_js.ADAPTER.key: html_css_js.ADAPTER,
    flutter.ADAPTER.key: flutter.ADAPTER,
    jetpack_compose.ADAPTER.key: jetpack_compose.ADAPTER,
    swiftui.ADAPTER.key: swiftui.ADAPTER,
}
