import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-md space-y-4 py-16 text-center">
      <h1 className="text-2xl font-bold">
        Page not found <span lang="hi" className="mt-1 block text-xl text-indigo-800">पेज नहीं मिला</span>
      </h1>
      <p className="text-sm text-slate-600">
        The link may be old, or the files were deleted. / <span lang="hi">लिंक पुराना हो सकता है, या फ़ाइलें हटा दी गई हैं।</span>
      </p>
      <Link href="/" className="inline-flex min-h-11 items-center rounded-lg bg-indigo-700 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-800">
        Upload a book / किताब अपलोड करें
      </Link>
    </div>
  );
}
