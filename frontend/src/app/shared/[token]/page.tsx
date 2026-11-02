import type { Metadata } from "next";
import { SharedTranscript } from "@/components/shared-transcript";

// Token nằm trên URL nên không để lọt qua Referer, và không cho công cụ tìm kiếm lập chỉ mục.
export const metadata: Metadata = {
  title: "Bản ghi được chia sẻ",
  referrer: "no-referrer",
  robots: { index: false, follow: false },
};

export default async function SharedPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <SharedTranscript token={token} />;
}
