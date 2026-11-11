import { LocaleProvider } from './providers/LocaleProvider';
import { Bootstrap } from './bootstrap/Bootstrap';

/** Own connection authority and restore only the backend's acknowledged workspace. */
export default function App() {
  return (
    <LocaleProvider>
      <Bootstrap />
    </LocaleProvider>
  );
}
