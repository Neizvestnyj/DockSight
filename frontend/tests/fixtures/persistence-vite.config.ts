import { mergeConfig } from 'vite';
import config from '../../vite.config';

const target = process.env.DOCKSIGHT_TEST_BACKEND_ORIGIN;
if (!target) throw new Error('The persistence fixture must allocate its backend first.');

// Preserve the application's changeOrigin proxy behavior while assigning only the owned backend.
export default mergeConfig(config, { server: { proxy: { '/api': { target } } } });
