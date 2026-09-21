// Runs pre-toolchain under whatever Node is active, so it must stay plain
// CJS with no transpile step — hence require() over import.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { engines } = require("../package.json");

// npm only checks engines.node on install/ci, not on `npm run test`, so a
// stale node_modules plus a fresh shell without `nvm use` skips straight to
// vitest/std-env's cryptic ERR_REQUIRE_ESM crash. Keep this range in sync
// with engines.node and .nvmrc.
const [major, minor] = process.versions.node.split(".").map(Number);
const satisfies = (major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22;

if (!satisfies) {
  console.error(
    `Node ${process.version} does not satisfy the required engines.node range "${engines.node}".\n` +
      "Run `nvm use` in frontend/ (see frontend/.nvmrc) to switch to the pinned version, then retry.",
  );
  process.exit(1);
}
