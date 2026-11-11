/** Format every observation as an explicit UTC timestamp. */
export function utc(value: string | null, includeDate = false): string {
  if (!value) return 'Unavailable';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Unavailable';
  const text = date
    .toISOString()
    .slice(includeDate ? 0 : 11, 19)
    .replace('T', ' ');
  return `${text} UTC`;
}

/** Keep byte units consistent without converting unavailable values to zero. */
export function bytes(value: number | null, locale = 'en', unavailable = 'Unavailable'): string {
  if (value === null) return unavailable;
  if (value === 0) return '0 B';
  const unit = value >= 1_073_741_824 ? 1_073_741_824 : 1_048_576;
  return `${(value / unit).toLocaleString(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} ${unit === 1_073_741_824 ? 'GiB' : 'MiB'}`;
}
