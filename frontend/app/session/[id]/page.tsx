import { Suspense } from "react";

import SessionView from "@/components/SessionView";

export default function SessionPage() {
  return (
    <Suspense>
      <SessionView />
    </Suspense>
  );
}
