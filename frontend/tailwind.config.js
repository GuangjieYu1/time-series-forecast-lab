/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#101820",
        panel: "#f6f8fb",
        accent: "#0f766e",
        timesfm: "#d946ef"
      }
    }
  },
  plugins: []
};
