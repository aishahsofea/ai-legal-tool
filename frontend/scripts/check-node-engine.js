// Must run as plain CJS with no transpile step, before vitest loads.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { engines } = require("../package.json");

// Mirrors engines.node — npm only enforces that on install/ci, not `npm test`.
const [major, minor] = process.versions.node.split(".").map(Number);
const satisfies = (major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22;

if (!satisfies) {
  console.error(
    `Node ${process.version} does not satisfy the required engines.node range "${engines.node}".\n` +
      "Run `nvm use` in frontend/ (see frontend/.nvmrc) to switch to the pinned version, then retry.",
  );
  process.exit(1);
}
