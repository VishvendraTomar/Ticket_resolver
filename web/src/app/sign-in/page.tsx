"use client";

import { SignIn } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { CenteredPage, Loading } from "@/components/status";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuthClient } from "@/lib/auth/context";
import { signInDev } from "@/lib/auth/fake-provider";
import { devIdentityFor } from "@/lib/auth/fake-token";

function DevSignIn() {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    try {
      signInDev(devIdentityFor(email, name));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid input");
    }
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardTitle>Sign in (development)</CardTitle>
        <CardDescription>
          No password: the same email always signs in as the same person.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="alice@example.com"
              required
              autoFocus
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="name">Name (optional)</Label>
            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <Button type="submit">Sign in</Button>
        </form>
      </CardContent>
    </Card>
  );
}

export default function SignInPage() {
  const auth = useAuthClient();
  const router = useRouter();

  useEffect(() => {
    if (auth.state.status === "signed-in") router.replace("/");
  }, [auth.state.status, router]);

  let body;
  if (auth.state.status !== "signed-out") body = <Loading />;
  else if (auth.provider === "clerk") body = <SignIn routing="hash" forceRedirectUrl="/" />;
  else body = <DevSignIn />;

  return <CenteredPage>{body}</CenteredPage>;
}
