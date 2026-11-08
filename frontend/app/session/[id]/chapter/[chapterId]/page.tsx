import { Suspense } from "react";

import ReviewView from "@/components/ReviewView";

export default function ReviewPage() {
  return (
    <Suspense>
      <ReviewView />
    </Suspense>
  );
}
