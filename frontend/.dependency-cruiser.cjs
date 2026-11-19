const modules = ['session', 'investigations', 'runtime', 'actions', 'model-selection', 'system-status'];

module.exports = {
  forbidden: [
    { name: 'no-cycles', severity: 'error', from: {}, to: { circular: true } },
    {
      name: 'shared-is-independent',
      severity: 'error',
      from: { path: '^src/shared/' },
      to: { path: '^src/(app|modules|infrastructure)/' },
    },
    {
      name: 'infrastructure-is-independent',
      severity: 'error',
      from: { path: '^src/infrastructure/' },
      to: { path: '^src/(app|modules)/' },
    },
    {
      name: 'infrastructure-uses-neutral-shared-code',
      severity: 'error',
      from: { path: '^src/infrastructure/', pathNot: '\\.test\\.[jt]sx?$' },
      to: { path: '^src/shared/', pathNot: '^src/shared/(contracts/|lib/format\\.ts$)' },
    },
    {
      name: 'neutral-format-has-no-ui-dependencies',
      severity: 'error',
      from: { path: '^src/shared/lib/format\\.ts$' },
      to: { path: '^src/', pathNot: '^src/shared/contracts/' },
    },
    {
      name: 'production-does-not-import-test-code',
      severity: 'error',
      from: { path: '^src/', pathNot: '\\.test\\.[jt]sx?$' },
      to: { path: '\\.test\\.[jt]sx?$|^(test-utils|tests|live-tests)/' },
    },
    {
      name: 'production-local-dependencies-have-owners',
      severity: 'error',
      from: { path: '^src/', pathNot: '\\.test\\.[jt]sx?$' },
      to: { dependencyTypes: ['local'], pathNot: '^src/|^\\.\\./backend/tests/fixtures/diagnostics\\.json$' },
    },
    {
      name: 'modules-do-not-import-assembly-or-infrastructure',
      severity: 'error',
      from: { path: '^src/modules/', pathNot: '\\.test\\.[jt]sx?$' },
      to: { path: '^src/(app|infrastructure)/' },
    },
    ...modules.map((owner) => ({
      name: `${owner}-cross-module-boundary`,
      severity: 'error',
      from: { path: `^src/modules/${owner}/`, pathNot: '\\.test\\.[jt]sx?$' },
      to: {
        path: `^src/modules/(?!${owner}/)(?!${owner === 'investigations' ? '(?:actions/index\\.ts|runtime/presentation\\.ts)$' : 'a^'})`,
      },
    })),
    {
      name: 'app-uses-module-public-entries',
      severity: 'error',
      from: { path: '^src/app/', pathNot: '\\.test\\.[jt]sx?$' },
      to: { path: '^src/modules/[^/]+/(?!index\\.ts$)' },
    },
    {
      name: 'main-uses-assembly-and-styles-only',
      severity: 'error',
      from: { path: '^src/main\\.tsx$' },
      to: { path: '^src/', pathNot: '^(src/app/App\\.tsx$|src/shared/styles/)' },
    },
    {
      name: 'runtime-presentation-is-read-only',
      severity: 'error',
      from: { path: '^src/modules/runtime/presentation\\.ts$' },
      to: { path: '^src/', pathNot: '^src/modules/runtime/ui/RuntimeContent\\.tsx$' },
    },
    {
      name: 'bootstrap-is-entry-only',
      severity: 'error',
      from: { path: '^src/' },
      to: { path: '^src/main\\.tsx$' },
    },
  ],
  options: {
    doNotFollow: { path: 'node_modules' },
    tsPreCompilationDeps: true,
    tsConfig: { fileName: 'tsconfig.json' },
    enhancedResolveOptions: { exportsFields: ['exports'], conditionNames: ['import', 'default'] },
  },
};
