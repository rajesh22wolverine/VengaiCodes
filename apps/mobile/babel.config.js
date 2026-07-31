module.exports = function(api) {
  api.cache(true);
  return {
    presets: ["babel-preset-expo"],
    plugins: [
      [
        "module-resolver",
        {
          alias: { "@": "./src" },
        },
      ],
      // Must be listed last — react-native-reanimated's own requirement.
      "react-native-reanimated/plugin",
    ]
  };
};
