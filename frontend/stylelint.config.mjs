export default {
  extends: ['stylelint-config-standard'],
  rules: {
    // Prettier owns whitespace and keeps the existing media-query notation.
    'rule-empty-line-before': null,
    'at-rule-empty-line-before': null,
    'custom-property-empty-line-before': null,
    'declaration-empty-line-before': null,
    'comment-empty-line-before': null,
    'media-feature-range-notation': 'prefix',
    'selector-pseudo-class-no-unknown': [true, { ignorePseudoClasses: ['global', 'local'] }],
    'selector-class-pattern': '^[a-z][a-z0-9_-]*$',
    'value-keyword-case': ['lower', { ignoreKeywords: ['currentColor', 'optimizeLegibility'] }],
  },
};
