BEGIN;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE ROLE app_alice LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE ROLE app_bob LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE TABLE public.accounts (
 id text PRIMARY KEY, owner name NOT NULL,
 balance bigint NOT NULL CHECK(balance BETWEEN 0 AND 1000000000)
);
CREATE TABLE public.operations (
 owner name NOT NULL, operation_key text NOT NULL,
 payload jsonb NOT NULL, response jsonb, PRIMARY KEY(owner,operation_key)
);
CREATE TABLE public.bad_accounts(id text PRIMARY KEY,balance bigint NOT NULL);
ALTER TABLE public.accounts ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_read ON public.accounts FOR SELECT USING(owner=session_user);
GRANT SELECT ON public.accounts TO app_alice,app_bob;
REVOKE ALL ON public.operations,public.bad_accounts FROM PUBLIC,app_alice,app_bob;
CREATE FUNCTION public.transfer(p_key text,p_source text,p_destination text,p_amount bigint,p_fail boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
 who name := session_user;
 wanted jsonb;
 existing jsonb;
 saved jsonb;
 source_balance bigint;
 destination_balance bigint;
 n integer;
BEGIN
 IF who NOT IN ('app_alice','app_bob') THEN
  RAISE EXCEPTION 'caller denied' USING ERRCODE='42501';
 END IF;
 IF p_key IS NULL OR p_key !~ '^[a-z0-9-]{1,32}$'
 OR p_source IS NULL OR p_source !~ '^[a-z][a-z0-9-]{0,31}$'
 OR p_destination IS NULL OR p_destination !~ '^[a-z][a-z0-9-]{0,31}$'
 OR p_source=p_destination OR p_amount IS NULL OR p_amount<1 OR p_amount>1000000 OR p_fail IS NULL THEN
  RAISE EXCEPTION 'invalid request' USING ERRCODE='22023';
 END IF;
 -- Same-owner calls serialize, including operation capacity and same-key retries.
 -- Hash collisions can over-serialize different owners, not grant permission.
 PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(who::text,0));
 PERFORM id FROM public.accounts WHERE id IN(p_source,p_destination) AND owner=who ORDER BY id FOR UPDATE;
 GET DIAGNOSTICS n=ROW_COUNT;
 IF n<>2 THEN RAISE EXCEPTION 'resource unavailable' USING ERRCODE='P0001'; END IF;
 wanted:=pg_catalog.jsonb_build_object('source',p_source,'destination',p_destination,'amount',p_amount);
 SELECT payload,response INTO existing,saved FROM public.operations WHERE owner=who AND operation_key=p_key FOR UPDATE;
 IF FOUND THEN
  IF existing IS DISTINCT FROM wanted THEN RAISE EXCEPTION 'operation conflict' USING ERRCODE='22023'; END IF;
  IF saved IS NULL THEN RAISE EXCEPTION 'saved result unavailable' USING ERRCODE='XX000'; END IF;
  RETURN saved;
 END IF;
 IF (SELECT count(*) FROM public.operations WHERE owner=who)>=64 THEN
  RAISE EXCEPTION 'operation capacity' USING ERRCODE='54000';
 END IF;
 INSERT INTO public.operations VALUES(who,p_key,wanted,NULL);
 UPDATE public.accounts SET balance=balance-p_amount
 WHERE id=p_source AND owner=who AND balance>=p_amount RETURNING balance INTO source_balance;
 IF NOT FOUND THEN RAISE EXCEPTION 'source unavailable' USING ERRCODE='P0001'; END IF;
 IF p_fail THEN RAISE EXCEPTION 'fixture interruption after debit' USING ERRCODE='P0001'; END IF;
 UPDATE public.accounts SET balance=balance+p_amount
 WHERE id=p_destination AND owner=who AND balance<=1000000000-p_amount RETURNING balance INTO destination_balance;
 IF NOT FOUND THEN RAISE EXCEPTION 'destination unavailable' USING ERRCODE='P0001'; END IF;
 saved:=pg_catalog.jsonb_build_object('operation_key',p_key,'source',p_source,'destination',p_destination,
  'amount',p_amount,'source_balance',source_balance,'destination_balance',destination_balance);
 UPDATE public.operations SET response=saved WHERE owner=who AND operation_key=p_key;
 GET DIAGNOSTICS n=ROW_COUNT;
 IF n<>1 THEN RAISE EXCEPTION 'publication failed' USING ERRCODE='XX000'; END IF;
 RETURN saved;
END $$;
REVOKE ALL ON FUNCTION public.transfer(text,text,text,bigint,boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.transfer(text,text,text,bigint,boolean) TO app_alice,app_bob;
COMMIT;
