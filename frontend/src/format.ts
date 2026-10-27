/** Format every observation as an explicit UTC timestamp. */
export function utc(value: string | null): string {
  if (!value) return 'Unavailable';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Unavailable' : `${date.toISOString().slice(11, 19)} UTC`;
}

/** Keep byte units consistent without converting unavailable values to zero. */
export function bytes(value: number | null): string {
  if (value === null) return 'Unavailable';
  if (value === 0) return '0 B';
  const unit = value >= 1_073_741_824 ? 1_073_741_824 : 1_048_576;
  return `${(value / unit).toFixed(1)} ${unit === 1_073_741_824 ? 'GiB' : 'MiB'}`;
}
