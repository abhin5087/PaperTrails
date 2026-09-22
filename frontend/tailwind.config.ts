import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#F7F4EC",
        "paper-line": "#DEDACB",
        ink: "#1C2333",
        rule: "#37517E",
        "rule-light": "#7C93B8",
        stamp: "#A93B3B",
        register: "#3E7856",
        graphite: "#6B7280",
      },
      fontFamily: {
        serif: ["var(--font-source-serif)", "Georgia", "serif"],
        sans: ["var(--font-plex-sans)", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
