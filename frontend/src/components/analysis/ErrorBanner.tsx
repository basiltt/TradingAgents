interface ErrorBannerProps {
  message: string;
}

export function ErrorBanner({ message }: ErrorBannerProps) {
  return (
    <div role="alert" className="rounded-md border border-destructive bg-destructive/10 p-3 text-sm text-destructive">
      {message}
    </div>
  );
}
