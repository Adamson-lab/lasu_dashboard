import os

def force_inject_high_res_branding():
    template_dir = 'templates'
    
    # The new High-Res payload forces the browser to scale the JPG crisply
    hd_payload = """
    <link rel="icon" type="image/jpeg" sizes="32x32" href="{{ url_for('static', filename='lasu_logo.jpg') }}">
    <link rel="icon" type="image/jpeg" sizes="16x16" href="{{ url_for('static', filename='lasu_logo.jpg') }}">
    <link rel="apple-touch-icon" href="{{ url_for('static', filename='lasu_logo.jpg') }}">
"""
    
    updated_count = 0
    
    print("Initiating V2 High-Res Forced Branding Sequence...")
    
    for filename in os.listdir(template_dir):
        if filename.endswith('.html'):
            filepath = os.path.join(template_dir, filename)
            
            with open(filepath, 'r', encoding='utf-8') as file:
                content = file.read()
            
            # 1. Strip out the old, blurry, broken tags if they exist
            content = content.replace('', '')
            content = content.replace('<link rel="icon" type="image/jpeg" href="{{ url_for(\'static\', filename=\'lasu_logo.jpg\') }}">', '')
            
            # 2. Force inject the new HD payload (Looking specifically for our new tag, not just the filename)
            if 'HIGH-RES LASU BRANDING' not in content and '</head>' in content:
                new_content = content.replace('</head>', f'{hd_payload}</head>')
                
                with open(filepath, 'w', encoding='utf-8') as file:
                    file.write(new_content)
                    
                print(f"✅ HD Branding Injected: {filename}")
                updated_count += 1
                
    print("--------------------------------------------------")
    print(f"🚀 V2 MATRIX UPGRADE COMPLETE: {updated_count} files successfully forced with HD branding.")

if __name__ == '__main__':
    force_inject_high_res_branding()