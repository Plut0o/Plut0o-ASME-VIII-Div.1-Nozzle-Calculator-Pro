import streamlit as st
import pandas as pd
import math
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ======================== CONSTANTS & CONFIGURATION ========================
UG16_MINIMUMS = {
    "Pressure Vessel (Standard)": 1.5,
    "Unfired Steam Boiler": 6.35,
    "Non-Code Construction": 0.0
}

UG45_TABLE = [
    ('1/8', 6, 10.29, 1.51), ('1/4', 8, 13.72, 1.96),
    ('3/8', 10, 17.12, 2.02), ('1/2', 15, 21.34, 2.42),
    ('3/4', 20, 26.67, 2.51), ('1', 25, 33.40, 2.96),
    ('1¼', 32, 42.16, 3.12), ('1½', 40, 48.26, 3.22),
    ('2', 50, 60.33, 3.42), ('2½', 65, 73.03, 4.52),
    ('3', 80, 88.90, 4.80), ('3½', 90, 101.60, 5.02),
    ('4', 100, 114.30, 5.27), ('5', 125, 141.30, 5.73),
    ('6', 150, 168.28, 6.22), ('8', 200, 219.08, 7.16),
    ('10', 250, 273.05, 8.11), ('12', 300, 323.85, 8.34)
]

ALLOWABLE_STRESS_FACTOR = 1.5
STRESS_INTENSITY_FACTOR = 3.0

# ======================== HELPER FUNCTIONS ========================
def get_ug16_min_thickness(equipment_type, service_type, custom_min_enabled, custom_min):
    """Determine UG-16 minimum thickness considering equipment type, service, and custom minimum"""
    equipment_min = UG16_MINIMUMS.get(equipment_type, 0.0)
    service_min = 2.5 if service_type in ["Water", "Compressed Air", "Steam"] else 0.0
    custom = custom_min if custom_min_enabled else 0.0
    
    min_thickness = max(equipment_min, service_min, custom)
    
    ref_parts = []
    if equipment_min > 0:
        ref_parts.append(f"UG-16 for {equipment_type}")
    if service_min > 0:
        ref_parts.append(f"UG-16(b) for {service_type}")
    if custom_min_enabled and custom > 0:
        ref_parts.append(f"Custom specified minimum")
    ref = " + ".join(ref_parts) if ref_parts else "No UG-16 requirement"
    
    return min_thickness, ref

# ======================== CALCULATION ENGINE ========================
def calculate_shell_thickness(P: float, D: float, S: float, E: float) -> float:
    """Calculate shell thickness per UG-27"""
    return (P * D) / (2 * S * E - 1.2 * P)

def calculate_head_thickness(P: float, D: float, S: float, E: float, head_type: str) -> float:
    """Calculate head thickness per UG-32"""
    if head_type == "Hemispherical":
        return (P * D) / (4 * S * E - 0.4 * P)
    elif head_type == "Ellipsoidal":
        return (P * D) / (2 * S * E - 0.2 * P)
    elif head_type == "Torispherical":
        return (0.885 * P * D) / (S * E - 0.1 * P)
    else:
        raise ValueError("Invalid head type")

def calculate_nozzle_thickness(P: float, d: float, S: float, E: float) -> float:
    """Calculate nozzle thickness per UG-27"""
    return (P * d) / (2 * S * E - 1.2 * P)

def perform_stress_analysis(inputs):
    """Perform detailed stress analysis with scientific visualization"""
    results = {'stresses': {}}
    try:
        # Shell stress (circumferential)
        R = inputs['D'] / 2
        results['stresses']['shell'] = (
            inputs['P_int'] * R / 
            ((inputs['t'] - inputs['CA']) * inputs['E_shell'])
        )

        # Head stress
        results['stresses']['head'] = (
            inputs['P_int'] * inputs['D'] / 
            (4 * (inputs['th_head'] - inputs['CA']) * inputs['E_head'])
        )

        # Nozzle stress
        results['stresses']['nozzle'] = (
            inputs['P_int'] * (inputs['d']/2) / 
            ((inputs['tn'] - inputs['CA']) * inputs['E_nozzle'])
        )

    except Exception as e:
        results['errors'].append(f"Stress analysis error: {str(e)}")
    return results

def perform_load_analysis(inputs):
    """Perform detailed load analysis with scientific visualization"""
    results = {'loads': {}}
    try:
        dn = inputs['d']
        tn = inputs['tn'] - inputs['CA']
        
        # Combined load calculations
        axial_stress = inputs['Fz'] / (math.pi * dn * tn)
        bending_stress = (4 * math.sqrt(inputs['Mx']**2 + inputs['My']**2)) / (math.pi * dn**2 * tn)
        shear_stress = math.sqrt(inputs['Fx']**2 + inputs['Fy']**2) / (math.pi * dn * tn)
        
        # Von Mises equivalent stress
        equivalent_stress = math.sqrt(
            (axial_stress + bending_stress)**2 +
            3 * shear_stress**2
        )
        
        results['loads'] = {
            'axial': axial_stress,
            'bending': bending_stress,
            'shear': shear_stress,
            'equivalent': equivalent_stress,
            'allowable': inputs['S_nozzle'] * ALLOWABLE_STRESS_FACTOR,
            'status': equivalent_stress <= (inputs['S_nozzle'] * ALLOWABLE_STRESS_FACTOR)
        }

    except Exception as e:
        results['errors'].append(f"Load analysis error: {str(e)}")
    return results

def calculate_asme_compliance(inputs):
    """Main ASME compliance calculation function"""
    results = {
        'steps': [], 'warnings': [], 'errors': [],
        'ug16': {}, 'ug37': {}, 'ug45': {}, 'head': {},
        'stresses': {}, 'loads': {}, 'calculations': {}
    }

    try:
        # ======================== INPUT VALIDATION ========================
        required_keys = ['P_int', 'D', 'd', 't', 'tn', 'th_head', 'CA',
                        'nozzle_od', 'E_shell', 'E_head', 'E_nozzle',
                        'S_shell', 'S_head', 'S_nozzle', 'equipment_type',
                        'head_type', 'Fx', 'Fy', 'Fz', 'Mx', 'My', 'Mz',
                        'service_type', 'custom_min_enabled', 'custom_min']
        missing = [key for key in required_keys if key not in inputs]
        if missing:
            raise ValueError(f"Missing inputs: {', '.join(missing)}")

        # ======================== COMPONENT CALCULATIONS ========================
        # Shell calculations
        results['calculations']['shell'] = {
            'required': calculate_shell_thickness(
                inputs['P_int'], inputs['D'],
                inputs['S_shell'], inputs['E_shell']
            ),
            'actual': inputs['t'] - inputs['CA']
        }

        # Head calculations
        results['calculations']['head'] = {
            'required': calculate_head_thickness(
                inputs['P_int'], inputs['D'],
                inputs['S_head'], inputs['E_head'],
                inputs['head_type']
            ),
            'actual': inputs['th_head'] - inputs['CA']
        }

        # Nozzle calculations
        results['calculations']['nozzle'] = {
            'required': calculate_nozzle_thickness(
                inputs['P_int'], inputs['d'],
                inputs['S_nozzle'], inputs['E_nozzle']
            ),
            'actual': inputs['tn'] - inputs['CA']
        }

        # ======================== UG-16 MINIMUM THICKNESS ========================
        min_thickness, ref = get_ug16_min_thickness(
            inputs['equipment_type'],
            inputs['service_type'],
            inputs['custom_min_enabled'],
            inputs['custom_min']
        )
        
        results['ug16'] = {
            'shell': {
                'required': min_thickness,
                'actual': inputs['t'] - inputs['CA'],
                'status': (inputs['t'] - inputs['CA']) >= min_thickness
            },
            'head': {
                'required': min_thickness,
                'actual': inputs['th_head'] - inputs['CA'],
                'status': (inputs['th_head'] - inputs['CA']) >= min_thickness
            },
            'nozzle': {
                'required': min_thickness,
                'actual': inputs['tn'] - inputs['CA'],
                'status': (inputs['tn'] - inputs['CA']) >= min_thickness
            },
            'reference': ref
        }

        # ======================== UG-45 NOZZLE THICKNESS ========================
        sorted_table = sorted(UG45_TABLE, key=lambda x: x[2])
        for nps, dn, od, thickness in sorted_table:
            if od >= inputs['nozzle_od']:
                tn_table = thickness + inputs['CA']
                break
        else:
            tn_table = sorted_table[-1][3] + inputs['CA']
        
        results['ug45'] = {
            'required': max(results['calculations']['nozzle']['required'], tn_table),
            'actual': inputs['tn'],
            'status': inputs['tn'] >= max(results['calculations']['nozzle']['required'], tn_table),
            'matched_size': f"NPS {nps}" if 'nps' in locals() else "NPS 12+"
        }

        # ======================== STRESS & LOAD ANALYSIS ========================
        results.update(perform_stress_analysis(inputs))
        results.update(perform_load_analysis(inputs))

        # ======================== FINAL COMPLIANCE ========================
        results['compliant'] = all([
            results['ug16']['shell']['status'],
            results['ug16']['head']['status'],
            results['ug16']['nozzle']['status'],
            results['ug45']['status'],
            results['stresses']['shell'] <= inputs['S_shell'],
            results['stresses']['head'] <= inputs['S_head'],
            results['stresses']['nozzle'] <= inputs['S_nozzle'],
            results.get('loads', {}).get('status', False)
        ])

    except Exception as e:
        results['errors'].append(f"Calculation error: {str(e)}")
    
    return results

# ======================== STREAMLIT UI COMPONENTS ========================
def equipment_type_selection():
    """Display equipment type selection radio buttons"""
    return st.radio(
        "Equipment Type:",
        options=list(UG16_MINIMUMS.keys()),
        help="Select equipment type per ASME UG-16 requirements"
    )

def material_properties_section():
    st.subheader("Material Properties")
    col1, col2, col3 = st.columns(3)
    with col1:
        S_shell = st.number_input("Shell Allowable Stress (MPa)", 
                                min_value=10.0, value=138.0, step=10.0)
        E_shell = st.slider("Shell Joint Efficiency", 0.1, 1.0, 1.0, step=0.05)
    with col2:
        S_head = st.number_input("Head Allowable Stress (MPa)", 
                               min_value=10.0, value=138.0, step=10.0)
        E_head = st.slider("Head Joint Efficiency", 0.1, 1.0, 1.0, step=0.05)
    with col3:
        S_nozzle = st.number_input("Nozzle Allowable Stress (MPa)", 
                                 min_value=10.0, value=118.0, step=10.0)
        E_nozzle = st.slider("Nozzle Joint Efficiency", 0.1, 1.0, 1.0, step=0.05)
    return S_shell, E_shell, S_head, E_head, S_nozzle, E_nozzle

def create_stress_distribution_plot(results, inputs):
    """Create enhanced stress visualization with subplots"""
    fig = make_subplots(
        rows=1, cols=3,
        subplot_titles=("Shell Stress", "Head Stress", "Nozzle Stress"),
        specs=[[{'type': 'indicator'}, {'type': 'indicator'}, {'type': 'indicator'}]]
    )
    
    # Shell stress gauge
    fig.add_trace(go.Indicator(
        mode="gauge+number+delta",
        value=results['stresses']['shell'],
        title={"text": "Shell Stress<br>(MPa)"},
        gauge={
            'axis': {'range': [0, inputs['S_shell']*1.2], 'tickwidth': 1},
            'bar': {'color': "#2a9d8f"},
            'steps': [
                {'range': [0, inputs['S_shell']], 'color': "#a7c957"},
                {'range': [inputs['S_shell'], inputs['S_shell']*1.2], 'color': "#bc4749"}
            ],
            'threshold': {
                'line': {'color': "black", 'width': 4},
                'thickness': 0.75,
                'value': inputs['S_shell']
            }
        }
    ), row=1, col=1)

    # Head stress gauge
    fig.add_trace(go.Indicator(
        mode="gauge+number+delta",
        value=results['stresses']['head'],
        title={"text": "Head Stress<br>(MPa)"},
        gauge={
            'axis': {'range': [0, inputs['S_head']*1.2], 'tickwidth': 1},
            'bar': {'color': "#2a9d8f"},
            'steps': [
                {'range': [0, inputs['S_head']], 'color': "#a7c957"},
                {'range': [inputs['S_head'], inputs['S_head']*1.2], 'color': "#bc4749"}
            ],
            'threshold': {
                'line': {'color': "black", 'width': 4},
                'thickness': 0.75,
                'value': inputs['S_head']
            }
        }
    ), row=1, col=2)

    # Nozzle stress gauge
    fig.add_trace(go.Indicator(
        mode="gauge+number+delta",
        value=results['stresses']['nozzle'],
        title={"text": "Nozzle Stress<br>(MPa)"},
        gauge={
            'axis': {'range': [0, inputs['S_nozzle']*1.2], 'tickwidth': 1},
            'bar': {'color': "#2a9d8f"},
            'steps': [
                {'range': [0, inputs['S_nozzle']], 'color': "#a7c957"},
                {'range': [inputs['S_nozzle'], inputs['S_nozzle']*1.2], 'color': "#bc4749"}
            ],
            'threshold': {
                'line': {'color': "black", 'width': 4},
                'thickness': 0.75,
                'value': inputs['S_nozzle']
            }
        }
    ), row=1, col=3)

    fig.update_layout(
        height=400,
        margin=dict(t=100, b=50),
        paper_bgcolor="rgba(0,0,0,0)",
        font={'color': "#2b2d42"}
    )
    return fig

def create_load_analysis_plot(results):
    """Create enhanced load analysis visualization"""
    fig = go.Figure()
    load_types = ['Axial', 'Bending', 'Shear', 'Equivalent']
    colors = ['#457b9d', '#e9c46a', '#2a9d8f', '#e76f51']
    
    fig.add_trace(go.Bar(
        x=load_types,
        y=[results['loads']['axial'], results['loads']['bending'],
           results['loads']['shear'], results['loads']['equivalent']],
        marker_color=colors,
        texttemplate="%{y:.1f} MPa",
        textposition='outside'
    ))
    
    fig.add_hline(
        y=results['loads']['allowable'],
        line_dash="dot",
        line_color="#bc4749",
        annotation_text=f"Allowable: {results['loads']['allowable']:.1f} MPa"
    )
    
    fig.update_layout(
        title="Nozzle Load Stress Analysis",
        yaxis_title="Stress (MPa)",
        xaxis_title="Load Type",
        plot_bgcolor='rgba(240,240,240,0.8)',
        paper_bgcolor="rgba(0,0,0,0)",
        font={'color': "#2b2d42"},
        hoverlabel=dict(bgcolor="white")
    )
    return fig

# ======================== MAIN APP ========================
def main():
    st.set_page_config(page_title="ASME Nozzle Calculator Pro", 
                      page_icon="📐",
                      layout="wide",
                      initial_sidebar_state="expanded")
    st.title("📐 ASME VIII Div.1 Nozzle Calculator Pro")
    
    with st.form("main_form"):
        # Input Section
        st.header("Design Parameters")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            P_int = st.number_input("Design Pressure (MPa)", min_value=0.1, value=2.0)
            D = st.number_input("Shell Diameter (mm)", min_value=50.0, value=1000.0)
            t = st.number_input("Shell Thickness (mm)", min_value=1.0, value=12.0)
            th_head = st.number_input("Head Thickness (mm)", min_value=1.0, value=12.0)
            head_type = st.selectbox("Head Type", ["Hemispherical", "Ellipsoidal", "Torispherical"])
        
        with col2:
            d = st.number_input("Nozzle Diameter (mm)", min_value=10.0, value=200.0)
            tn = st.number_input("Nozzle Thickness (mm)", min_value=1.0, value=10.0)
            nozzle_od = st.number_input("Nozzle OD (mm)", value=114.3)
            CA = st.number_input("Corrosion Allowance (mm)", value=1.5)
            S_shell, E_shell, S_head, E_head, S_nozzle, E_nozzle = material_properties_section()
        
        with col3:
            eq_type = equipment_type_selection()
            service_type = st.selectbox(
                "Service Type:",
                options=["Water", "Compressed Air", "Steam", "Other"],
                help="Select service type per UG-16(b) requirements"
            )
            custom_min_enabled = st.checkbox("Enable Custom Minimum Thickness")
            custom_min = st.number_input(
                "Custom Minimum Thickness (mm):",
                min_value=0.0, value=2.5, step=0.1,
                disabled=not custom_min_enabled
            )
            st.subheader("Applied Loads")
            Fx = st.number_input("Shear Force X (N)", value=0.0)
            Fy = st.number_input("Shear Force Y (N)", value=0.0)
            Fz = st.number_input("Axial Force Z (N)", value=0.0)
            Mx = st.number_input("Bending Moment X (N·mm)", value=0.0)
            My = st.number_input("Bending Moment Y (N·mm)", value=0.0)
            Mz = st.number_input("Torsional Moment Z (N·mm)", value=0.0)
        
        submitted = st.form_submit_button("🚀 Perform Full Verification")

    if submitted:
        inputs = {
            'P_int': P_int, 'D': D, 't': t, 'th_head': th_head,
            'd': d, 'tn': tn, 'nozzle_od': nozzle_od, 'CA': CA,
            'S_shell': S_shell, 'E_shell': E_shell,
            'S_head': S_head, 'E_head': E_head,
            'S_nozzle': S_nozzle, 'E_nozzle': E_nozzle,
            'equipment_type': eq_type, 'service_type': service_type,
            'custom_min_enabled': custom_min_enabled, 'custom_min': custom_min,
            'head_type': head_type,
            'Fx': Fx, 'Fy': Fy, 'Fz': Fz, 'Mx': Mx, 'My': My, 'Mz': Mz
        }
        
        with st.spinner("Performing ASME compliance verification..."):
            results = calculate_asme_compliance(inputs)
            
            if results.get('errors'):
                st.error("## ❌ Critical Errors Detected")
                for error in results['errors']:
                    st.error(f"- {error}")
                return
            
            # Results Display
            st.header("Compliance Report")
            status_color = "green" if results['compliant'] else "red"
            st.markdown(f"## Overall Status: :{status_color}[{'COMPLIANT' if results['compliant'] else 'NON-COMPLIANT'}]")
            
            with st.expander("📌 Component Thickness Analysis", expanded=True):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.subheader("Shell")
                    st.metric("Required Thickness", f"{results['calculations']['shell']['required']:.2f} mm")
                    st.metric("Actual Thickness", f"{results['calculations']['shell']['actual']:.2f} mm")
                with col2:
                    st.subheader("Head")
                    st.metric("Required Thickness", f"{results['calculations']['head']['required']:.2f} mm")
                    st.metric("Actual Thickness", f"{results['calculations']['head']['actual']:.2f} mm")
                with col3:
                    st.subheader("Nozzle")
                    st.metric("Required Thickness", f"{results['calculations']['nozzle']['required']:.2f} mm")
                    st.metric("Actual Thickness", f"{results['calculations']['nozzle']['actual']:.2f} mm")

            with st.expander("⚖️ Stress Analysis", expanded=True):
                st.plotly_chart(create_stress_distribution_plot(results, inputs), use_container_width=True)
            
            with st.expander("🔩 Load Analysis", expanded=True):
                st.plotly_chart(create_load_analysis_plot(results), use_container_width=True)
            
            with st.expander("⚙️ Detailed Compliance Checks"):
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("UG-16 Minimum Thickness")
                    df = pd.DataFrame({
                        "Component": ["Shell", "Head", "Nozzle"],
                        "Minimum (mm)": [
                            results['ug16']['shell']['required'],
                            results['ug16']['head']['required'],
                            results['ug16']['nozzle']['required']
                        ],
                        "Actual (mm)": [
                            results['ug16']['shell']['actual'],
                            results['ug16']['head']['actual'],
                            results['ug16']['nozzle']['actual']
                        ],
                        "Status": [
                            "✅ Pass" if x else "❌ Fail" for x in [
                                results['ug16']['shell']['status'],
                                results['ug16']['head']['status'],
                                results['ug16']['nozzle']['status']
                            ]
                        ]
                    })
                    st.dataframe(df.style.applymap(lambda x: "background-color: #e9f5db" if x == "✅ Pass" else "background-color: #ffcccb", subset=["Status"]),
                                use_container_width=True)
                    st.caption(f"Reference: {results['ug16']['reference']}")
                
                with col2:
                    st.subheader("UG-45 Nozzle Requirements")
                    st.metric("Required Thickness", f"{results['ug45']['required']:.2f} mm", 
                             delta=f"{results['ug45']['actual'] - results['ug45']['required']:.2f} mm Margin")
                    st.metric("Matched Size", results['ug45']['matched_size'])
                    st.metric("Status", "✅ Compliant" if results['ug45']['status'] else "❌ Non-compliant")

if __name__ == "__main__":
    main()