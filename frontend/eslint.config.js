import { globalIgnores } from 'eslint/config'
import pluginVue from 'eslint-plugin-vue'
import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'

// Flat config for the Finance-God frontend (Vue 3 + TypeScript).
// Enforces Vue essential correctness rules and the recommended TS rule set.
export default defineConfigWithVueTs(
  { files: ['**/*.{ts,mts,tsx,vue}'] },
  globalIgnores(['**/dist/**', '**/node_modules/**', 'config/**']),
  pluginVue.configs['flat/essential'],
  vueTsConfigs.recommended,
  {
    rules: {
      // "Masthead" is a deliberate newspaper-domain term for this UI and does not
      // collide with any HTML element, so it is exempt from the multi-word rule.
      'vue/multi-word-component-names': ['error', { ignores: ['Masthead'] }],
      // The codebase leans on inferred types and occasional pragmatic escapes;
      // keep these as warnings so lint stays actionable rather than noisy.
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },
)
