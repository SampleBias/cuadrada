-- Enable Row Level Security for storage
ALTER TABLE storage.buckets ENABLE ROW LEVEL SECURITY;
ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;

-- Create policies for the uploads bucket
CREATE POLICY "Allow public access to uploads bucket" 
ON storage.buckets FOR SELECT 
USING (name = 'uploads');

CREATE POLICY "Allow public uploads to uploads bucket" 
ON storage.objects FOR INSERT 
WITH CHECK (bucket_id = (SELECT id FROM storage.buckets WHERE name = 'uploads'));

CREATE POLICY "Allow public read for uploads bucket" 
ON storage.objects FOR SELECT 
USING (bucket_id = (SELECT id FROM storage.buckets WHERE name = 'uploads'));

-- Create policies for results bucket
CREATE POLICY "Allow public access to results bucket" 
ON storage.buckets FOR SELECT 
USING (name = 'results');

CREATE POLICY "Allow public uploads to results bucket" 
ON storage.objects FOR INSERT 
WITH CHECK (bucket_id = (SELECT id FROM storage.buckets WHERE name = 'results'));

CREATE POLICY "Allow public read for results bucket" 
ON storage.objects FOR SELECT 
USING (bucket_id = (SELECT id FROM storage.buckets WHERE name = 'results'));

-- Optional: Allow delete if needed
CREATE POLICY "Allow public delete for uploads bucket" 
ON storage.objects FOR DELETE 
USING (bucket_id = (SELECT id FROM storage.buckets WHERE name = 'uploads'));

CREATE POLICY "Allow public delete for results bucket" 
ON storage.objects FOR DELETE 
USING (bucket_id = (SELECT id FROM storage.buckets WHERE name = 'results'));

-- Allow update if needed
CREATE POLICY "Allow public update for uploads bucket" 
ON storage.objects FOR UPDATE 
USING (bucket_id = (SELECT id FROM storage.buckets WHERE name = 'uploads'));

CREATE POLICY "Allow public update for results bucket" 
ON storage.objects FOR UPDATE 
USING (bucket_id = (SELECT id FROM storage.buckets WHERE name = 'results')); 