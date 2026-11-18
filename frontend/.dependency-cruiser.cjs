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
        path: `^src/modules/(?!${owner}/)(?!${owner === 'investigations' ? '(actions|runtime)/index\\.' : 'a^'})`,
      },
    })),
    {
      name: 'app-uses-module-public-entries',
      severity: 'error',
      from: { path: '^src/app/', pathNot: '\\.test\\.[jt]sx?$' },
      to: { path: '^src/modules/[^/]+/(?!index\\.)' },
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
