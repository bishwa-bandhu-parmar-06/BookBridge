import { Suspense } from "react";

import StudyReader from "@/components/StudyReader";

export default function ReadPage() {
  return (
    <Suspense>
      <StudyReader />
    </Suspense>
  );
}
