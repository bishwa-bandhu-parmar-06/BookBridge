"use client";

export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="mx-auto max-w-md space-y-4 py-16 text-center">
      <h1 className="text-2xl font-bold">
        Something went wrong <span lang="hi" className="mt-1 block text-xl text-indigo-800">कुछ गड़बड़ हो गई</span>
      </h1>
      <p className="text-sm text-slate-600">
        Please try again. / <span lang="hi">कृपया फिर से कोशिश करें।</span>
      </p>
      <button
        type="button"
        onClick={reset}
        className="inline-flex min-h-11 items-center rounded-lg bg-indigo-700 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-800"
      >
        Try again / फिर कोशिश करें
      </button>
    </div>
  );
}
