/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,jsx}"],
  theme: { extend: {
    colors: { maker: { blue: "#2f5e9e", red: "#c13f4a", canvas: "#f7f6f2", paper: "#fffdf8", ink: "#2f2e2a", muted: "#6f6e69", line: "#d8d5cd" } },
    boxShadow: { panel: "0 18px 45px rgba(47, 46, 42, 0.10)" },
    fontFamily: { sans: ["var(--font-fira-sans)", "system-ui", "sans-serif"], mono: ["var(--font-fira-code)", "monospace"] },
  } },
  plugins: [],
};
