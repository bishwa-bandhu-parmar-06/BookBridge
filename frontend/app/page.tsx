import { Suspense } from "react";

import UploadForm from "@/components/UploadForm";

export default function Home() {
  return (
    <Suspense>
      <UploadForm />
    </Suspense>
  );
}
