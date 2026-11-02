"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useWorkspace } from "@/components/workspace-provider";

/** Giữ cho đường dẫn cũ: tải file giờ là hộp thoại mở trên trang đang xem. */
export default function NewJobPage() {
  const router = useRouter();
  const { openUpload } = useWorkspace();

  useEffect(() => {
    openUpload();
    router.replace("/jobs");
  }, [openUpload, router]);

  return null;
}
