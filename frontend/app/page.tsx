import { redirect } from 'next/navigation';

// Root / always redirects to /chat
export default function RootPage() {
  redirect('/chat');
}
